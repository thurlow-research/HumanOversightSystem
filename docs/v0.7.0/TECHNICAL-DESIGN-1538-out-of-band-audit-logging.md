# TECHNICAL DESIGN — #1538: out-of-band audit logging (one writer, one reader, one sync; the `audit-log` ref never reaches `main`)

**Issue:** #1538 (`build`, milestone v0.7.0)
**Author:** `technical-design`
**Date:** 2026-09-25
**Iteration:** 2 of 5 (CORE cap)
**Status:** **DRAFT, revised after the `spec-red-team` review. Waiting on architect review.** Slices
marked "blocked on ESC-n" (§15) must not be built until a human answers. The other slices can go to
the coder once the architect approves.
**Branch:** `worker-1538-oob-audit-logging-design-260925053001-3107911`

**Iteration-2 revision log** (spec-red-team findings F1–F4, plus one self-found overclaim):

| Finding | What changed | Sections |
|---|---|---|
| **F1 CRITICAL** — union reader + free-form `record` lets a worker forge an overseer's review/idempotency record | **TD-D4 is reversed.** `read_stream` stays local-only, exactly as today. Every decision-bearing read (the named questions, `bounce_count`, `step_range`) reads **only the asker's own clone** and counts a record only when its envelope provenance matches the question (`role`, `writer`). The branch union is reachable only through the generic `query`, which is labelled non-authoritative for suppression. `idempotent-skip` is removed from the attestable set. `pr-reviewed` never counts `record`-written records. `record` cross-checks `--app` against `HOS_CYCLE_ROLE`. **I state plainly that none of this is unforgeable while both roles run as one OS user under `bypassPermissions`; that is raised as ESC-6.** | §0 (TD-VF-16), §4.2, §4.3, §5.1–§5.3, §7, §13.2, §14 (TD-O4 rewritten, TD-O8), §15 (ESC-1 changed, ESC-6 new), §16 |
| **F2 HIGH** — `post_comment.sh` exit 4 breaks `run_release_panel.sh:186-189` | Exit 4 and the required write now apply **only when the caller passes `--kind`**. Without `--kind`, every existing exit code is byte-unchanged and the event is best-effort. All callers are enumerated with their handling. `submit_pr.sh` gets **no** new exit code, which is now stated explicitly. A §13.2 re-review row is added. | §0 (TD-VF-17), §9.1, §13.2, §14 (TD-O5), §16 |
| **F3 MEDIUM** — "vacuously satisfied" contradicts the fail rule | Reworded: "(b) raises no violation". An absent `audit-log` ref **passes**, with the disclosure line. | §8.2 |
| **F4 LOW** — a single quote cannot be passed as one literal token | Literal argv values are restricted to a quote-free, space-free character class. Free text (release titles, summaries) goes only through file arguments (`--release-file`, `--json-file`). | §5.2, §5.3, §9.3, §12 |
| **Self-found** — §5.3/§12 claimed `python3 -m …audit_log append` is "not allowlisted for agents" | False: the policy grants `Bash(python3 *)`, and cron runs with `bypassPermissions`. The claim is withdrawn. The control is now reader-side provenance plus clone separation (F1 row). | §5.3, §12 |

**Binding inputs (the spec). Nothing below re-opens them:**

1. **The #1538 issue body.** Requirements R1–R4:
   - **R1:** one shared audit implementation, used by both roles. It writes local `audit/log/**`
     files and does no git operations.
   - **R2:** audit events are written by the doing-scripts as a forced side effect.
   - **R3:** the cron job pushes to the `audit-log` branch. The current `_sync_audit_logs` is
     extracted into a hardened standalone script.
   - **R4:** `audit-log` is never merged into `main`.

   Also in scope: the backlog sweep. Out of scope: no new App identity, no gate exception, and no
   change to protected-surface PR approval. #1538 supersedes #1157/ADR-035 and #1095's
   backlog-recovery item, and #1517 retargets onto this mechanism.
2. **The human process ruling, 2026-09-10.** `pm-agent` and the dual-lens panel are skipped. The
   requirements are the issue body plus the rulings.
3. **Ruling Q2 / CR-1, 2026-09-10.** The read side becomes a real CLI:
   - one filtered query, server-side, runnable as a single command with literal arguments;
   - higher-level named-question CLIs for the #849 idempotency-precheck class, built on the generic
     read primitive.

   The write-side ruling is unchanged.
4. **ADR-1357 AD-10** (and its 2026-09-14 clarification). Mutation wrappers write their own events
   in the halt-on-failure order: post → confirm → append → finalize. `bounce_count` must move to
   CR-1's filtered read by changing **one function**.
5. **ADR-1542 AD-20** and **REQUIREMENTS-1542 §3.3.** #1542 builds no audit CLI and blocks on this
   issue rather than forking a second reader. CR-1's argv shape applies. The VF-1 defect
   (`cycle_log` hardcodes `role: "worker"`) is handed to this issue.

> This document specifies **contracts, not code**. Every "must" is a requirement on the
> implementation. Where a binding input is explicit, this document restates it in implementable
> terms. Where it leaves a choice to `technical-design`, the choice is made here and labelled
> **TD-D<n>** with its reason. Choices that belong to the architect are **TD-O<n>** (§14). Choices
> that belong to a human are **ESC-n** (§15).

---

## 0. Verification findings — what exists today (searched before designing)

Searched: `bin/`, `bootstrap/` (including `lib/`), `scripts/` recursively (including
`scripts/automation/lib/*.py` and `scripts/oversight/lib/`), `.github/workflows/`, `.claude/agents/`,
the two cron prompts, and `contract/`. Search terms: `audit/log`, `audit_log`, `oversight-log.jsonl`,
`_sync_audit_logs`, `audit-log`, `write_event`, `read_stream`, `cycle_log`. I also inspected the
remote ref `origin/audit-log` and the `audit/` state of the Worker, Overseer and Human clones directly.
All line numbers are from `origin/main` at `a80e70613`.

### 0.1 The shared writer and reader R1 asks for already exist — this issue extends them, it does not create them

- **TD-VF-1 — `scripts/oversight/lib/audit_log.py` is already the only serializer.** It exposes:
  - `canonical_bytes`: sorted-key compact JSON plus `\n`;
  - `record_relpath`: `<YYYY>/<MM>/<ts>-<slug>-<sha256[:12]>.json`, content-addressed;
  - `write_event`: write-once and idempotent, using `open("xb")`;
  - `read_stream`: glob + sort + re-canonicalize; fails loud on invalid JSON (#1533).

  It also has a CLI with two subcommands. `write` takes the event on **stdin**; `read` prints an
  **unfiltered** stream. The Bash facade `scripts/oversight/lib/audit_log.sh` can only be
  **sourced**. Those are exactly REQ-1542 VF-4's three shape defects. **R1 is structurally
  satisfied today.** What is missing is (a) a write API with an envelope and typed argv, (b) a
  filtered reader, and (c) cross-clone visibility.
- **TD-VF-2 — every current writer goes through that module.** No second serializer exists. The
  complete inventory:

  | Writer | Site | Event(s) |
  |---|---|---|
  | `bin/hos-cron` `_audit` → `cycle_log` | `bin/hos-cron:362-365` (≈45 call sites) | `cycle-*` |
  | `scripts/automation/lib/cycle_log.py` `log_event` | `:57-66` | any; **hardcodes `"role":"worker"`** (VF-1) |
  | `scripts/automation/lib/stale_commit_detector.py` | `:26`, `:283` via `log_event` | `pre-pr-stale-commits` |
  | `scripts/automation/agent_invoke_cli.py` | `:1011-1015`, `:1227` | `agent-invocation` |
  | `scripts/automation/lib/merge_authority.py` `record_pr_bounce` | `:1262` | `pr-bounced` |
  | `scripts/oversight/record_agent_model.py` | `:111` | `subagent-model-resolved` |
  | `scripts/oversight/suspension_manager.py` | `:321` | suspension events |
  | `scripts/oversight/release_artifact_logic.py` | `:561-562` | release artifact validation |
  | `scripts/oversight/run_with_retry.sh` | `:119` (`audit_write_event … 2>&1 \|\| true`) | `validator-failure` |
  | `bootstrap/submit_pr.sh` `_hos_audit_stale_base_merge` | `:79-95`, called `:204` | `stale-base-merged` |
  | `bootstrap/lib/branch_ownership.sh` | `:281-301` | `branch-ownership-refused` |
  | `scripts/run_redteam_sample.sh` | `:307-309` | `sampling-audit` |
  | **Agent prose** (sourced facade) | `overseer.md:155, :163, :214, :317, :492, :692-693` | `human-authorized-merge`, `pr-merged-without-review`, `release-gate-validation`, `human-approval-detected`, CODEOWNERS-gate log, `human-required` |
  | **Agent prose, retired path** | `worker.md:894-905` | `ng3b-violation-attempt` → *"append to `audit/oversight-log.jsonl`"*, a file retired by #888 P5. **This is a live defect:** the event is written to a path no reader looks at. |

- **TD-VF-3 — every current reader goes through `read_stream`, and then filters by hand.**
  - `merge_authority.bounce_count` (`:1131-1149`) scans every record in Python.
  - `check_pr_reviewed.sh` (`:55-101`) runs `audit_read_stream | python3 -c …`.
  - `scripts/oversight/lib/step_range.sh:44` runs `audit_read_stream | grep`.
  - `audit_conditional_proceed.sh:117` runs `audit_read_stream` in a loop through `jq`.
  - Agent prose at `overseer.md:154, :161, :181-182` and `overseer-cron-prompt.md:38` runs
    `source … audit_log.sh` + `audit_read_stream | grep -F … | grep -F …`. That is three
    constructs a sandbox allowlist cannot match (REQ-1542 VF-5).

  **Every reader sees only the local clone's `audit/log/`.** The overseer cannot see the worker's
  records.

### 0.2 The sync path, and what the `audit-log` ref actually contains

- **TD-VF-4 — `_sync_audit_logs` (`bin/hos-cron:367-427`, invoked once at `:2168`).** It:
  - fetches `origin audit-log main`;
  - bases on `origin/audit-log`, or on `origin/main` if `ls-remote` fails;
  - checks out a throwaway detached **worktree** of the whole base tree;
  - copies each local record whose path is absent there, commits, and pushes
    `HEAD:refs/heads/audit-log` without `--force`.

  Its failure handling:
  - a fetch failure returns 0 silently;
  - push stderr goes to `2>/dev/null`;
  - there is no retry within a cycle.

  Its header comment (`:371-373`) claims *"A GitHub Actions workflow reads from that branch and
  commits only those files to main."* **No such workflow exists.** `.github/workflows/` holds ten
  workflows and none reads `audit-log`. The comment is false, and it describes the exact behavior
  R4 forbids.
- **TD-VF-5 — the remote `audit-log` branch.** It holds **31,548** records under `audit/log/`, all
  of which parse as JSON objects (verified by reading every blob). 743 records lack `timestamp`;
  most use `ts`, as in the `ng3b` schema. It also carries **666 non-audit files**: a snapshot of
  framework source from when it forked off `main`. Its first-parent history reaches `main` commit
  `aa41d7c51` (2026-08-09). Since then it has accumulated only `chore(audit): sync logs` commits.
  **441 records have non-canonical, hand-written names** (e.g.
  `20260909T184650Z-pr-review-skipped-idempotent-1527.json`, no date dashes and no hash). Agents
  wrote these with a file-write tool. The latest one is dated 2026-09-09.
- **TD-VF-6 — event-name drift is real and it defeats today's idempotency check.** September's
  records on the branch include `pr-review` (74), `pr-review-skipped-idempotent` (81),
  `idempotent-skip` (28), `pr-reviewed` (6), `idempotent-skip-pr1512` (2), `pr-review-skipped` (1),
  `pr-review-duplicate-comment` (2) and more. These are improvised names for the same few facts.
  `check_pr_reviewed.sh`'s `REVIEWED_EVENTS = {"pr-review","human-required","idempotent-skip"}`
  silently misses the others. **An unconstrained agent-issued write surface produces this drift.**
  §5.3 closes it.
- **TD-VF-7 — `main` currently tracks 7,927 records under `audit/log/`.** All of them were added by
  one merge, `823cea532` (PR #1582, 2026-09-11), almost certainly through `git add -A`. **All 7,927
  are also present on `audit-log`.** Checked by path. For the untracked files in §0.3, checked
  byte-for-byte by blob id.

### 0.3 The backlog is noise, not data loss (measured 2026-09-25)

| Clone | Untracked `audit/…` files | Not on `audit-log` (by path) | Same path, different bytes |
|---|---|---|---|
| Worker | 6,433 | **4** (written since the last sync) | 0 |
| Overseer | 2,760 | **3** | 0 |
| Human | 7,740 (HEAD is at 2026-08-17; 7,739 of these are files `main` now tracks) | **1** | 0 |

- **TD-VF-8 — "thousands of unsynced audit files" (#1803) is almost entirely a visibility
  problem.** The records are on the branch. They show as untracked because nothing tells git to
  ignore them. This has a concrete operational cost beyond noise. `bootstrap/hos_repo_sync.sh:137`
  treats any `git status --porcelain` output as a dirty tree, and so degrades to fetch-only. **Any
  clone that has written a single audit record can therefore never be fast-forwarded by
  `hos_repo_sync.sh`.** The genuinely unsynced backlog is 8 records. The Human clone has no sync
  path at all, because it does not run `hos-cron`.
- **TD-VF-9 — the Human clone never pushes.** `hos-human` has no sync step. Its records reach the
  branch only by accident, through the `main`-tracked set.

### 0.4 Other findings the design must honor

- **TD-VF-10 — `pre_pr_stale_check.py:51-54, :67-78` is stale in two ways.** Its
  `_AUDIT_ONLY_FILES` guards `audit/oversight-log.jsonl` and `audit/overnight-loop-log.md`. The
  first was retired by #888; the second has no writer anywhere (grep finds no producer). Its
  docstring repeats the non-existent "GitHub Actions sync workflow". The docstring also says these
  files "are gitignored", and they are not: `.gitignore` has no `audit` entry.
- **TD-VF-11 — ADR-035's artifacts are dead code.** `scripts/framework/audit_predicate.py` and
  `audit_allowlist.txt` were built for the audit-approval bot that #1538 supersedes. They have no
  importer outside their own test.
- **TD-VF-12 — `bootstrap/pr_review.sh` (#1657) writes no audit event.** It is a mutation wrapper
  that ADR-1357-AMENDMENT-1 says slice 4 calls, and it has no AD-10 audit event. The verdict event
  (`pr-review`) is still written by agent prose. This is a startup-gap finding (§13).
- **TD-VF-13 — the repository is a shallow clone** (`git rev-parse --is-shallow-repository` →
  `true`). Every git operation below must work in a shallow repository.
- **TD-VF-14 — performance headroom for a full scan is large.** `git cat-file --batch` over all
  31,548 branch blobs (5.48 MB, mean 174 B) takes **0.19 s** wall time. A full, unfiltered-by-path
  scan is affordable. See TD-D3.
- **TD-VF-15 — cycle-start fetch already refreshes `origin/audit-log`.** `bin/hos-cron:146` runs
  `git fetch origin`, and `remote.origin.fetch` is `+refs/heads/*:refs/remotes/origin/*`. Every
  cycle therefore starts with a fresh remote-tracking `audit-log` ref, at no extra cost.
- **TD-VF-16 (iteration 2) — no in-process role identity is unforgeable today.** Five facts combine:
  - Worker and overseer cron sessions launch with `claude --print --permission-mode
    bypassPermissions` (`bin/hos-cron:1781`).
  - `gen_sandbox_config.py` does not yet generate a policy for either role (REQ-1542 VF-12).
  - Even the human policy grants `Bash(python3 *)` (`docs/SANDBOX-POLICY.md:166`), which states
    that the OS sandbox, not the allowlist, is the security boundary.
  - All three clones and all three App keys belong to one OS user.
  - This worker session could read the Overseer clone's working tree during verification.

  Consequences:
  - Any envelope field (`role`, `writer`) and any environment variable (`HOS_CYCLE_ROLE`) can be set
    by a process that wants to forge it.
  - An agent can write a file under any clone's `audit/log/`.
  - Each role's **clone directory** is today's only real separation, and it is enforced by
    convention, not by the OS.

  F1 turns on this, and §5.4 states what the design can and cannot guarantee.
- **TD-VF-17 (iteration 2) — callers of `bootstrap/post_comment.sh` and `bootstrap/submit_pr.sh`.**
  Found by grep over `bin/`, `scripts/`, `bootstrap/`, `.claude/agents/`, the cron prompts and
  `tests/`.
  - **Script caller of `post_comment.sh`:** exactly one, `scripts/run_release_panel.sh:186-189`. It
    treats **any** nonzero exit as `post-failed` and exits 5. (`scripts/run_panel.sh:971` is a
    comment only.)
  - **Prose callers of `post_comment.sh`:**
    - `worker.md`: `:129, :286, :343, :658, :709, :833, :878, :882, :885, :887`;
    - `overseer.md`: `:726, :803`.
  - **Tests exercising `post_comment.sh`:**
    - `tests/automation/test_post_comment.py`;
    - `tests/oversight/test_release_panel_shell.py`;
    - `tests/automation/test_comment_format_check.py`;
    - `tests/framework/test_overseer_verdict_artifact.py`.
  - **Callers of `submit_pr.sh`:** prose only (`worker.md:130, :383, :435`,
    `worker-cron-prompt.md:136`) plus its tests. No script calls it.

---

## 1. What this issue delivers, and what it does not

**Delivers:**

- an extended L1 audit library: a typed append API with an envelope, atomic publication, and a
  filtered query. The query's source policy (local, or local + the `audit-log` ref) is fixed per call
  site, and it has a provenance filter;
- the agent-facing read CLI: a union `query` for information, plus four local-only,
  provenance-filtered named questions for decisions (CR-1);
- a closed-enum agent-attestation write, for the residual prose-mandated events;
- a standalone sync script that pushes to `audit-log` using git plumbing and never touches a
  worktree;
- forced side-effect events in the doing-scripts;
- `main`/`audit-log` segregation: `.gitignore` plus a CI gate;
- prose migration;
- backlog sweep verification.

**Does not deliver:**

| Not in #1538 | Owner |
|---|---|
| The #1357 slice-4 mutation wrappers (`overseer_merge.sh`, `overseer_escalate.sh`, `overseer_bounce.sh`, `overseer_embargo.sh`) | #1357. They **call** this issue's `append_event(required=True)` (§3). This issue adds no call site to scripts that do not exist. |
| Exposing a `trail_present` discriminator in `merge_authority_cli bounce-count`'s envelope (TD-1357 §14.6 residual) | #1357 slice 4. This issue makes it available in L1 (§4.3). See TD-O6. |
| The #1542 sandbox allowlist artifact (`gen_sandbox_config.py` for worker/overseer) | #1542. This issue guarantees its entry points are allowlistable (§12). |
| Untracked second-review prompt artifacts (#1762/#1769/#1782) | Those issues. The artifacts live outside `audit/log/**`, and this design neither ignores nor syncs them. |
| Retiring `audit_predicate.py` / `audit_allowlist.txt` (TD-VF-11) | Recommended follow-up issue. It touches `scripts/framework/**` and has its own tests. |
| Local pruning of records after they are pushed | Not done (TD-D6). |

---

## 2. Layer map (concrete paths)

| Layer | Path | New/Mod | Role |
|---|---|---|---|
| L1 lib | `scripts/oversight/lib/audit_log.py` | mod | Serializer (unchanged); `append_event`; atomic publish; `query_events` (required per-call-site `sources`, provenance filter); `read_stream` unchanged |
| L1 facade | `scripts/oversight/lib/audit_log.sh` | mod | Adds `audit_append` (argv passthrough) for **committed Bash scripts only**. Agents never source it. |
| L1 lib | `scripts/oversight/lib/audit_sync.py` | new | Sync logic (plumbing) + `--status` |
| L3 | `bootstrap/audit_sync.sh` | new | Thin wrapper. The sole sync entry point, for `hos-cron`, `hos-human`, and humans. |
| L2 | `scripts/oversight/audit_query_cli.py` | new | Agent-facing: `query`, named questions, `record` |
| L3 | `bootstrap/audit.sh` | new | Thin wrapper. The **only** agent-facing audit command. |
| Gate | `scripts/oversight/gates/audit_segregation.sh` + `scripts/oversight/audit_segregation_logic.py` | new | R4 enforcement in CI |

**TD-D1 — follow the #1357/#1657 layering.** Agent-facing surfaces get a `bootstrap/*.sh` L3 wrapper
and an L2 Python CLI; logic lives in Python. Reasons:

- It keeps every agent-facing command under `bootstrap/**`, which is protected and human-gated,
  like `merge_authority.sh`, `pr_review.sh` and `query_issues.sh`.
- The #1542 allowlist enumerates exactly these entry points.
- The internal `python3 -m scripts.oversight.lib.audit_log append` surface is **not** allowlisted
  for agents. That is what makes the closed `record` enum (§5.3) enforceable rather than advisory.

---

## 3. Write side — the L1 contract

### 3.1 `append_event` (new, `audit_log.py`)

```
append_event(event: str, fields: Mapping[str, JSONValue], *, root: str, writer: str,
             role: Optional[str] = None, required: bool = True) -> Optional[str]
```

**Record built:**

```
{"event", "timestamp", "role", "cycle_id"?, "writer", **fields}
```

serialized by the existing `canonical_bytes`. Field rules:

| Field | Rule |
|---|---|
| `timestamp` | One `now()` read, UTC, `YYYY-MM-DDTHH:MM:SSZ` (the existing format). The filename `ts` is derived from it through the existing `_resolve_ts`. |
| `role` | Precedence: explicit `role` > env `HOS_CYCLE_ROLE` > `"unknown"`. **Never a hardcoded default.** This closes VF-1. |
| `cycle_id` | Env `HOS_CYCLE_ID` if set and matching `^[A-Za-z0-9._-]+$`; otherwise the key is omitted. |
| `writer` | Required. The emitting script's repo-relative path, or `<path>:<subcommand>`. This is provenance for later audits; no reader filters on it in this issue. |

**Validation.** Every violation raises `ValueError`, and a CLI maps it to exit 2:

- `event` matches `^[a-z0-9][a-z0-9-]{0,63}$`;
- field keys match `^[a-z_][a-z0-9_]{0,63}$`;
- `fields` must not contain a reserved key (`event`, `timestamp`, `role`, `cycle_id`, `writer`);
- values are JSON-serializable;
- `len(canonical_bytes(record)) ≤ 65536`.

**Secret refusal.** No string value, at any depth, may match the GitHub-token pattern that
`scripts/automation/pr_review_cli.py:98` uses. On a match, raise `ValueError("refusing to record a
credential-shaped value in field <key>")`. **The value is never altered.** A record is evidence, and
a silently redacted record is a falsified one. It is refused instead. Records are pushed to a GitHub
branch, so this check is load-bearing (see TD-O2 on sharing the pattern).

**`required` semantics:**

- `True`: every failure (validation, I/O, hash collision) propagates as an exception.
- `False`: any exception is caught. The function writes **one** line to stderr,
  `audit: WARN: <event> not recorded: <reason>`, and returns `None`. It never raises and never
  suppresses the diagnostic.

**`write_event` stays unchanged in signature and behavior**, except for the atomic publication
below. It is the path for pre-shaped events (migration, `release_artifact_logic`). `append_event`
calls it.

### 3.2 Atomic publication (modifies `write_event`)

Today `open("xb")` followed by `write()` exposes a window in which the final filename exists and is
empty or partial. A sync running concurrently (§7, finding C-5) can copy that partial file.
Required replacement:

1. Write the bytes to `<dir>/.<name>.tmp-<pid>-<8 random hex>`. The leading dot and the non-`.json`
   suffix mean no `*.json` glob can match it. Then `fsync`.
2. `os.link(tmp, final)`. This is atomic and fails if the target exists.
3. On `FileExistsError`: if the final file's bytes equal the new bytes, this is the idempotent
   no-op. Otherwise raise `RuntimeError` (hash collision), exactly as today.
4. `unlink(tmp)` in a `finally`.

Readers and the sync must ignore every dot-prefixed file. A temp file older than 1 hour is debris
from a killed writer. The sync (§6.2 step 0) deletes it; nothing else does.

### 3.3 Typed argv CLI (for committed Bash scripts)

```
python3 -m scripts.oversight.lib.audit_log append --root <path> --writer <name> --event <slug>
        [--required] [--str k=v]... [--int k=N]... [--bool k=true|false]... [--json-file <path>]
```

- `--json-file` supplies an object that is merged into `fields`. Duplicate keys across flags are a
  usage error.
- **Typing is explicit (TD-D2).** `cycle_log`'s auto-coercion (`int(v)` when parseable) turns an
  all-digit `head_sha` into an integer, which silently breaks equality matching. The new CLI never
  guesses a type.
- **Exit codes:** 0 = written or idempotent (stdout is the relpath); 2 = usage/validation; 5 =
  write failure when `--required` is given. Without `--required`, a write failure prints the WARN
  line and exits **0** with empty stdout.

The facade `audit_append <args…>` in `audit_log.sh` passes arguments through verbatim, using the
same `cd "$repo" && python3 -m …` idiom as `audit_write_event`.

### 3.4 `cycle_log.py` (VF-1)

- `log_event` sets `role` from `HOS_CYCLE_ROLE`, falling back to `"unknown"`.
- A caller-supplied `role=` keyword still wins.
- Positional parsing is unchanged, including the legacy int coercion, which existing `cycle-*` event
  shapes depend on.

---

## 4. Read side — L1: one reader, two sources

### 4.1 Sources

| Source | What | Freshness |
|---|---|---|
| `local` | Regular, non-dot `*.json` files under `<root>/audit/log/` in the working tree (tracked or untracked) | Immediate |
| `branch` | Blobs under `audit/log/` in the tree of `refs/remotes/origin/audit-log` in `<root>`'s repository | As of the last fetch. This is cycle start (TD-VF-15), or the last successful sync push, which updates the remote-tracking ref. |

The `branch` source is **present** only when all three hold:

1. `git -C <root> rev-parse --show-toplevel` succeeds;
2. its `realpath` equals `realpath(root)`, so a temp test root nested inside some other repository
   is never mistaken for that repository;
3. `git rev-parse --verify --quiet refs/remotes/origin/audit-log^{commit}` succeeds.

Otherwise the source is absent, and the reason is recorded in the trail disclosure (§4.3). Absence is
not an error.

**Reading the branch:**

- `git ls-tree -r -z <commit> -- audit/log/` gives paths and blob ids;
- one `git cat-file --batch` process streams the blobs;
- paths whose basename starts with `.` are skipped;
- no worktree and no checkout.

### 4.2 Union and ordering

- **Dedup key:** the relpath under `audit/log/`.
  - Same relpath and same bytes → one record, `source: "both"`.
  - Same relpath and **different** bytes → both records are kept, each tagged with its source, and
    the conflict is counted (§4.3).
- **TD-D4 (revised in iteration 2 for F1): `read_stream(root)` is unchanged and local-only.** Its
  signature, its source (the local working tree only) and its ordering stay byte-identical.
  Iteration 1 made it a union. That was the change that turned a forged record in one clone into a
  live answer in another (F1), so it is withdrawn.
  - **One implementation, with a source policy fixed per call site.** Both sources go through one
    function, `query_events`, which takes a **required** keyword `sources`. It has no default, so
    every call site states its policy in code.
  - **No CLI flag can change it** (TD-D5). This keeps AD-20's single-reader property: there is one
    reader function, and the only thing that varies is a policy frozen in code and reviewed with the
    call site.
  - **Decision-bearing call sites are local-only:** the four named questions, `bounce_count`,
    `step_range`, and `check_pr_reviewed.sh`.
  - **Only the generic `query` (§5.1) and `audit_sync --status` read the branch.**
- **Malformed records:** a record that is not a JSON object raises `ValueError` naming the source and
  relpath. This is today's fail-loud (#1533), extended to the branch source. The sync refuses to
  push malformed files (§6.2), so the shared branch cannot be poisoned by a single bad local write.
- `sources` is reachable from Python only, and no CLI exposes it (§5.1, TD-D5). A test enumerates
  every `query_events` call site in `scripts/` and pins its `sources` value. Changing a call site's
  policy is therefore a visible, reviewed diff.

### 4.3 `query_events` and the trail disclosure

```
query_events(root, *, sources: tuple[str, ...], events: Sequence[str] = (),
             match: Mapping[str, str] = {}, since: Optional[str] = None,
             until: Optional[str] = None,
             provenance: Optional[Provenance] = None) -> QueryResult
count_events(root, *, sources: tuple[str, ...], event: str, match: Mapping[str, str] = {},
             provenance: Optional[Provenance] = None) -> int
Provenance = {role: str, writers: frozenset[str], accept_legacy: bool}
```

- `sources` is `("local",)`, `("branch",)` or `("local","branch")`. It is required and has no
  default.
- `provenance`, when given, counts a record only if both hold:
  - `record.role == provenance.role` **and** `record.writer ∈ provenance.writers`; or the record
    has **no** `writer` key, `accept_legacy` is true, and the record came from the local source.
  - The legacy branch preserves today's answers for pre-envelope history, which today's readers
    already trust unconditionally.
- Records excluded by provenance are counted in `provenance_excluded` and never silently dropped.

**Filter semantics:**

- `events` are OR'ed; an empty list means any event.
- `match` entries are AND'ed.
- A `match` entry `k=v` holds when `record[k]` is a JSON scalar whose **canonical string form**
  equals `v`. The canonical string forms are:

  | Record value | Canonical form |
  |---|---|
  | string | itself |
  | int | decimal |
  | bool | `true` / `false` |
  | null | `null` |

  Non-scalar values never match. This is the whole typing rule, so `pr=1234` matches both `1234`
  and `"1234"`.
- `since` and `until` are inclusive bounds on the record's time. The time is `timestamp`, else `ts`,
  normalized with `normalize_ts`. When a time bound is given, a record with neither field, or an
  unparseable one, is excluded and counted in `untimed_excluded`.

**`QueryResult` fields:**

- `records`: each `{relpath, source, record}`, sorted by (normalized time or `""`, relpath);
- `scanned`;
- `untimed_excluded`;
- `trail`:
  - `local`: `{dir_present, records}`;
  - `branch`: `{present, absent_reason, ref, commit, commit_time, records}`;
  - `duplicates`;
  - `conflicts`;
  - `trail_present`: `local.records + branch.records > 0`.

**TD-F1 closure (for #1357).** `trail_present: false` is the "no trail" discriminator that TD-1357
§14.6 found missing: a lost trail can now be told apart from "zero bounces". This issue computes it.
Surfacing it in the `bounce-count` envelope is #1357's to do (TD-O6).

**`bounce_count` — the AD-10 one-function swap (in S1).** The body of
`merge_authority.bounce_count(cid, *, repo_root=".")` (`:1131-1149`) becomes
`return _AUDIT_LOG.count_events(repo_root, sources=("local",), event="pr-bounced", match={"cid": cid})`.
Nothing else in `merge_authority.py` changes: not the signature (AD-1), not `record_pr_bounce`, and
not the loader. `tests/automation/test_bounce_gate.py` must pass **unmodified**.

**Why local-only (iteration 2).** It gives exactly today's semantics, so no #1357 sign-off is
disturbed. A union would also let another clone's forged `pr-bounced` records inflate the count.
That fails toward earlier human escalation, which is safe, but it is still an answer another
principal could steer.

**TD-D3 — no filename-based prefilter.** It is tempting to prefilter on the `<slug>` in the filename.
That would be correct only for names produced by `write_event`, and TD-VF-5 shows 441 names that
were not. A filename whose slug disagrees with its content would then be silently missed. That is a
wrong answer to "did this already happen", and it lands exactly on the #849 class. Full scans cost
0.19 s today (TD-VF-14).

**Performance budget, enforced by a test on a synthetic 100k-record fixture:** `query_events` must
finish in under 5 s. If record volume ever breaks that budget, the fix is an index keyed by content,
designed then. It is never a name prefilter.

---

## 5. Read side — the agent-facing CLI (CR-1)

**Literal-argv rule (F4, iteration 2).** This applies to every value passed on the command line to
`bootstrap/audit.sh`:

- **Scalar values** (`--pr`, `--head-sha`, `--number`, `--kind`, `--event`, `--field k=v`,
  `--str k=v`, `--int k=v`, `--bool k=v`, `--since`, `--until`) must match
  `^[A-Za-z0-9._:/@#+=-]{1,200}$`. No spaces and no quotes of either kind. Any other value exits 2.
- **Free text** (a release title, a summary, a list of flags) is passed **only** through a file
  argument: `--release-file <path>` or `--json-file <path>`. The caller writes the file with a file
  tool, which needs no shell quoting.

As a result, no audit command ever needs a quoted token. §12's allowlist regex is correspondingly
quote-free.

### 5.1 Generic filtered query (union; informational, never authoritative for suppression)

```
bash bootstrap/audit.sh query --app <worker|overseer|human> [--event <slug>]... [--field k=v]...
     [--since <iso>] [--until <iso>] [--limit N] [--count] [--refresh]
```

- **Scope.** It reads `sources=("local","branch")`: the one surface that shows all clones' records.
  Every returned record carries `source`, and the record's own `role` and `writer` are
  **self-asserted** (TD-VF-16).
- **Output disclosure.** The output always includes `"authoritative_for_suppression": false`, and
  `not_verified` always contains `"provenance_self_asserted"`. **Prose must never use `query` to
  decide whether to skip an action. Only a §5.2 named question may do that.** T5.4 enforces this by
  scanning the prose.
- **Flags accepted:** `--app` is required on every subcommand, which gives a uniform, allowlistable
  argv shape (the ADR-1357 AD-2 rule). There is **no** `--root`, `--source` or `--repo-root`.
  - The repo root comes from the script's own location, as in `submit_pr.sh`.
  - Source selection is a policy-source selector (the TD-1357 §3.4.0 rule). **TD-D5:** any such flag
    exits 2.
- **`--refresh`:** runs `git fetch origin +refs/heads/audit-log:refs/remotes/origin/audit-log`, with
  stderr passed through, before reading. A fetch failure exits **5**.
- **`--limit N`:** default 50, range 1..1000. It returns the *latest* N matches and sets
  `truncated`.
- **`--count`:** omits `records`.
- **stdout:** exactly one JSON object:
  `{schema_version:1, subcommand, app_role, authoritative_for_suppression:false, query:{…}, matched, scanned, untimed_excluded, truncated, trail:{…}, records:[{relpath, source, record}]?, not_verified:[…], error:null|str}`.
  `not_verified` also contains:
  - `"branch_source_absent"` when the branch source is absent;
  - `"conflicting_records"` when `conflicts > 0`;
  - `"trail_empty"` when `trail_present` is false.
- **Exit codes:**

  | Code | Meaning |
  |---|---|
  | 0 | Answered, including zero matches. This is the reporter convention. |
  | 1 | Internal error |
  | 2 | Usage |
  | 4 | Trail unreadable: a malformed record, or a git read error |
  | 5 | Refresh failed |

  stderr is never suppressed.

### 5.2 Named questions (the #849 class) — decision-bearing, so local-only and provenance-filtered

Each named question is a fixed composition of
`query_events(sources=("local",), provenance=…)`. It is never its own reader, and it never reads
the branch. There is no `--refresh` on named questions, because it would be meaningless for a local
read.

| Subcommand | Question | Composition | Provenance: records counted |
|---|---|---|---|
| `pr-reviewed --pr N --head-sha S` | Has a review disposition been recorded for this exact head? | `events ∈ {pr-review, human-required, idempotent-skip}`, `pr=N`, (`head_sha=S` **or** `headSha=S`) | `role=overseer` **and** `writer = scripts/automation/pr_review_cli.py:submit-verdict`; **or** legacy (no `writer` key). **Records written by `bootstrap/audit.sh:record` are never counted**, which removes the F1 vector. |
| `decision-fired --pr N --event E [--head-sha S]` | Did disposition E already fire for this PR (at this head)? | `events={E}`, `pr=N`, optional head match. `E ∈ {pr-review, pr-bounced, human-authorized-merge, pr-merged-without-review, human-approval-detected}`; anything else exits 2. | Per `E`: `pr-review` → as `pr-reviewed`; `pr-bounced` → `role=overseer`, `writer=scripts/automation/lib/merge_authority.py:record_pr_bounce`, or legacy; the three attestations → `role=overseer`, `writer=bootstrap/audit.sh:record`, or legacy |
| `comment-posted --number N --kind K [--head-sha S]` | Did I already post a comment of this kind here? | `events={comment-posted}`, `number=N`, `kind=K`, optional `head_sha=S` | `role = --app`, `writer=bootstrap/post_comment.sh`. No legacy form exists. |
| `release-cleared --release-file <path>` | Was this release already cleared? The file holds the milestone title, UTF-8, one line, at most 200 characters. | `events={release-gate-validation}`, `release=<title>`, `decision=CLEARANCE` | `role=overseer`, `writer=bootstrap/audit.sh:record`, or legacy |

- **Output:**
  `{schema_version:1, subcommand, app_role, answer: bool, matches: int, provenance_excluded: int, latest: {relpath, event, timestamp, writer}|null, trail:{local:{…}}, not_verified:[…]}`.
  Exit codes are the same as §5.1 except that 5 is never returned.
  - `provenance_excluded > 0` adds `"provenance_mismatch_present"` to `not_verified`, so a forgery
    attempt is visible rather than silently ignored.
  - `local.records == 0` adds `"trail_empty"`.
- **Completeness.** Every event these questions count is written by the asking role, in the asking
  clone. Local files are never pruned (TD-D6), so local-only is complete. The one exception is a
  freshly re-created clone, which starts empty.
  - In that case the answer is `false`, and the failure direction is **a repeat action (the #849
    duplicate), never a skipped action**. `trail_empty` discloses it.
  - I accept this rather than read the branch, because reading the branch is exactly the F1 exposure.
- **`check_pr_reviewed.sh` (TD-D7).** Its logic is replaced by one `exec` of
  `audit_query_cli.py pr-reviewed --legacy-output …`. Its argv (`<pr#> <head_sha> [root]`), its
  one-line output shape and its exit codes are preserved, and it stays local-only, exactly as today.
  `tests/oversight/test_check_pr_reviewed.py` passes unmodified.
  - `--legacy-output` is a Python-only flag, not exposed through `bootstrap/audit.sh`.
  - The optional `[root]` argument keeps its current meaning.
  - `overseer-cron-prompt.md:54` keeps working unchanged.
- **Behavior change against today, disclosed.** Today `check_pr_reviewed.sh` counts **any** local
  record of the three events. After S4 it counts only legacy records plus forced `pr-review` records
  with the right provenance. Once §9.3 migrates the prose, new `human-required` records are written
  by `record` and are **no longer counted**. This is deliberate for F1.
  - It loses no coverage: `overseer.md` ("Ordering within step 6") posts the `submit-verdict` review
    **first** on every disposition, including HUMAN_REQUIRED. The forced `pr-review` record
    therefore exists for every head the overseer has reviewed since S5.
  - Between S4 and S5, the answer for newly reviewed heads is `false`. The precheck is corroborating
    only (`overseer-cron-prompt.md:58`), so that is a possible duplicate verdict, not a skipped one.
    **To close the window, S4 and S5 ship in the same release.** §17 orders them adjacently.
- **Not added: a `bounce-count` named question.** `merge_authority_cli bounce-count` already exists.
  A second one would be the two-answers class AD-20 forbids.
- **The event-name set for `pr-reviewed` is today's set, unchanged.** Whether to add the improvised
  historical names from TD-VF-6 is TD-O3.

### 5.3 `record` — the closed agent-attestation write

```
bash bootstrap/audit.sh record --app <role> --event <E> [--str k=v]... [--int k=N]... [--bool k=v]... [--json-file <path>]
```

This exists only for events that record an **agent observation with no doing-script behind it
yet**. For example, the between-cycle merge audit is still prose.

- **`E` must be in the closed attestable set**, held as a constant in `audit_query_cli.py` and listed
  below. Anything else exits **3** (refusal), *including every forced event*: `pr-review`,
  `pr-bounced`, `comment-posted`, `pr-opened`, `panel-run`, `second-review-run`, `validators-run`,
  and all `cycle-*`.
- **Role cross-check (iteration 2).**
  - If `HOS_CYCLE_ROLE` is set, `--app` must equal it.
  - If it is unset (an interactive session), `--app` must be `human`.
  - A mismatch exits 3 with `refusal_reason: "app_role_mismatch"`.

  **This is defense in depth against a mis-stated `--app` in prose. It is not a security boundary:
  the variable is settable by the caller (TD-VF-16).**
- **Envelope:** `role = --app`; `writer = "bootstrap/audit.sh:record"`; `required=True`. A write
  failure exits 5.
- **stdout:** `{schema_version, subcommand, app_role, relpath, event, error, refusal_reason}`.

| Attestable event | Prose site today | Counted by a named question? | Future owner, which removes it from this set |
|---|---|---|---|
| `human-authorized-merge` | `overseer.md:155` | `decision-fired` (overseer-local only) | #1542 merge-audit script |
| `pr-merged-without-review` | `overseer.md:163` | `decision-fired` (overseer-local only) | #1542 merge-audit script |
| `release-gate-validation` | `overseer.md:214` | `release-cleared` (overseer-local only) | #1542 release-gate script |
| `codeowners-gate-evaluated` (new name; `:492` names no event today) | `overseer.md:492` | no | #1357 slice 4 (the AD-10 "wrapper records that it ran") |
| `human-approval-detected` | `overseer.md:317` | `decision-fired` (overseer-local only) | #1357 slice 4 |
| `human-required` | `overseer.md:692` (SPEC-378 R3.3 trail) | **no**. Excluded from `pr-reviewed` by provenance. | #1357 slice 4 `overseer_escalate.sh` |
| `ng3b-violation-attempt` | `worker.md:894-905` (retired path; TD-VF-2) | no | worker release protocol script (#1542) |

- **`idempotent-skip` is removed (F1).** It had no mandated writer; it is improvised (TD-VF-6). Its
  only effect was to suppress a review. Legacy local records of it are still counted, preserving
  today's answers for history.
- When an owner script lands, the same PR removes the event from this set. A test pins the set, so
  removal is a visible, reviewed diff.

### 5.4 What F1's fix guarantees, and what it does not (stated without overclaiming)

**Closed by design** (these hold as long as each role acts only inside its own clone):

1. **Cross-role forgery through the CLI.** A worker session running
   `audit.sh record --app overseer --event … ` writes into the **worker's** clone. The only way that
   record leaves the clone is the worker's sync, which pushes it to the branch. No decision-bearing
   read looks at the branch. The overseer's `pr-reviewed` and `decision-fired` answers are therefore
   unchanged. *This is exactly F1's scenario, and it is closed.*
2. **Suppressing a review through an attestation.** `pr-reviewed` never counts a
   `record`-written record, so even a record written from inside the overseer's own clone through
   `record` cannot mark a head as reviewed.
3. **New event-name drift.** Closed enum plus a pinned test.

**Not closed, and not closable by this issue.** TD-VF-16 applies: one OS user, `bypassPermissions`,
and `Bash(python3 *)`. Given that:

- A process in the worker's session can write a file directly into the **Overseer clone's**
  `audit/log/` with forged `role` and `writer` fields, or call the internal `append` CLI with any
  `--writer`.
- It could equally edit `overseer.md` in that clone. That is a pre-existing exposure, and this
  design neither creates nor widens it.
- No envelope field, environment variable or file location inside one shared OS user and
  filesystem can prove which role wrote a record.
- A real guarantee needs OS-enforced separation (see ESC-6) or cryptographic attestation. The latter
  is out of scope, because it would need key material the forger could also read.

**ESC-6 carries this to a human.**

---

## 6. The standalone sync — `bootstrap/audit_sync.sh`

### 6.1 Entry point

```
bash bootstrap/audit_sync.sh                # sync
bash bootstrap/audit_sync.sh --dry-run      # compute; no object writes, no push
bash bootstrap/audit_sync.sh --status       # read-only report; no fetch, no push (#1517's signal)
```

- The repo root is derived from the script's location. There are no other flags, and no env-var
  selectors.
- **Credentials:** it uses whatever `git push` credentials the caller's environment carries (in cron,
  `hos_configure_git_credentials`, `bin/lib/git-credentials.sh`). It never mints a token and never
  places a token in argv or a URL.
- **stdout:** one JSON object:
  `{schema_version, mode, outcome, base_commit, new_commit, attempts, local_records, already_present, pushed_records, conflict_count, conflicts:[≤20 relpaths], rejected_count, rejected:[≤20 {relpath, reason}], nonconforming_names, error}`.
  `outcome` is one of `pushed | nothing_to_sync | degraded | contention | remote_failure | status`.
- **Exit codes:**

  | Code | Meaning |
  |---|---|
  | 0 | `pushed`, `nothing_to_sync` or `status` |
  | 1 | Internal |
  | 2 | Usage |
  | 3 | `degraded`: valid records were pushed, but conflicts or rejects remain |
  | 4 | `contention`: non-fast-forward after the maximum number of attempts |
  | 5 | `remote_failure`: fetch, auth or push failed for another reason |

### 6.2 Algorithm — git plumbing only; never a worktree, never the live index/HEAD

0. **Housekeeping.**
   - Delete this repo's temp index files (`$(git rev-parse --git-path hos-audit-sync.index.)*`)
     older than 1 hour.
   - Delete dot-temp publish files older than 1 hour under `audit/log/` (§3.2).
   - Delete nothing else, ever.
1. **Enumerate local candidates.** Regular, non-dot `*.json` files under `<root>/audit/log/`.
   `audit/overnight-loop-log.md` is **dropped** from the sync: it has no writer (TD-VF-10) and it
   is not write-once.
2. **Validate each candidate.**
   - Content must parse as a JSON object. Otherwise → `rejected` with `reason: "malformed"`, and it
     is never pushed.
   - If the name matches the canonical grammar
     `^\d{4}-\d{2}-\d{2}T\d{6}Z-[a-z0-9-]+-[0-9a-f]{12}\.json$`, the 12-hex suffix must equal
     `sha256(canonical_bytes(content))[:12]`. On a mismatch it is still pushed, because evidence is
     never dropped, but it is counted in `nonconforming_names`. Non-grammar names are also counted
     there.
3. **Fetch** `git fetch origin +refs/heads/audit-log:refs/remotes/origin/audit-log`, with stderr
   passed through.
   - If the remote branch does not exist (`git ls-remote --exit-code origin
     refs/heads/audit-log` → exit 2), then base = **none**.
   - **Any other fetch or ls-remote failure → `remote_failure`, exit 5.** **Never** fall back to
     `origin/main`. Today's fallback (`:388-389`) would base a new branch on framework source.
4. **Build.** Use a private temp index: `GIT_INDEX_FILE=<git-path>/hos-audit-sync.index.<pid>`,
   exported only to the plumbing subprocesses below.
   - `git read-tree <base>`, or `git read-tree --empty` when there is no base.
   - Get `git ls-tree -r -z <base> -- audit/log/` as a map from path to blob.
   - Get blob ids for all candidates with one `git hash-object -w --stdin-paths`.
   - For each candidate:
     - absent on base → stage it (`git update-index --index-info`, mode `100644`);
     - same blob → `already_present`;
     - **different blob → `conflict`. Never overwrite a path on the branch.**
5. **Nothing staged** → `nothing_to_sync` (exit 0, or 3 if there are conflicts or rejects).
6. **Commit.** `git write-tree`, then `git commit-tree <tree> [-p <base>] -m "chore(audit): sync <n>
   record(s) [role=<HOS_CYCLE_ROLE|unknown>] [cycle=<HOS_CYCLE_ID|none>]"`. With no base, the commit
   is a **root commit whose tree contains only `audit/log/**`** (TD-D8).
   - Author and committer come from the repo's configured identity.
   - If none is configured, use `HOS_BOT_LOGIN` if set, else `hos-audit-sync`. Either way the email
     is `<name>@users.noreply.github.com`.
7. **Push** `git push origin <commit>:refs/heads/audit-log`, **never `--force`**, stderr passed
   through.
   - **Non-fast-forward rejection:** go back to step 3 on the new tip. Blobs are already in the
     object store, so only the tree and commit are rebuilt. Up to **3 attempts** in total, sleeping
     `uniform(1,5) × attempt` seconds between them. When exhausted → `contention`, exit 4.
   - **Any other push failure** → `remote_failure`, exit 5, with no retry.
8. **On success**, git updates `refs/remotes/origin/audit-log` through the configured fetch refspec.
   The implementation must verify this with `rev-parse` and, if it did not happen, run
   `git update-ref` explicitly. This way the generic `query` (§5.1) sees the pushed records immediately.
9. A `finally` removes the temp index. **Local record files are never modified or deleted.**

**`--status`:**

- steps 0–2 plus a read of the last-fetched ref;
- no fetch and no push;
- reports `local_records`, `missing_on_branch` (count, plus ≤20 relpaths), `oldest_missing_ts`,
  `branch_commit` and `branch_commit_time`;
- works offline.

This is what #1517's liveness monitor consumes: *records exist locally that the branch lacks, and
the oldest is more than N hours old.*

**TD-D6 — local records are retained after a push.** Four reasons:

1. Pruning deletes audit evidence, which is irreversible. Retention costs about 175 B per record.
2. Local copies are a second copy if the branch is ever lost or rewritten (ESC-2).
3. Named questions are local-only (§5.2), so retention is what keeps their answers complete.
4. `.gitignore` already removes the noise (§8).

### 6.3 `bin/hos-cron` changes

- **`_sync_audit_logs` (`:367-427`) is deleted.** `:2168` becomes a call to
  `"$REPO_ROOT/bootstrap/audit_sync.sh"`, with stdout forwarded to the cycle log.
  - Exit 0: silent beyond the JSON line.
  - Any nonzero exit: print `"$LOG_PREFIX WARN: audit sync outcome=<outcome> exit=<n> (records
    retained locally; retried next cycle)"` and write `_audit audit-sync-failed outcome=<outcome>
    exit=<n>`. The event is written locally and pushed by a later cycle, which gives #1517 a
    positive failure signal.
  - **The cycle's own exit status is never affected.**
- **Token age.** The installation token minted at `:834` expires after 1 hour. A cycle longer than
  that would fail every push with `remote_failure`, forever (see the recorded "expired token" class).
  Before the sync call, if more than 45 minutes have passed since the mint, re-run the auth block's
  mint with the same tempfile pattern. A mint failure skips the sync with the WARN line plus
  `audit-sync-failed outcome=auth_expired`.
- **`_audit` (`:362-365`)** keeps `|| true`: it is best-effort by design (§10). It **drops
  `2>/dev/null`**, so failures print and are no longer silent.
- The false "GitHub Actions workflow … commits … to main" comment is removed.

---

## 7. Concurrency — the `_sync_audit_logs` claim, checked against the code

**The claim.** Content-addressed filenames plus skip-if-exists make it safe for the worker's and the
overseer's cycles to write and push around the same time.

**Verdict:** the claim holds for **safety** (no lost records, no overwritten records, no content
conflicts) for every record `write_event` produces, today and under the new call pattern. It does
**not** hold in five places. The new design closes each of them.

**Why it holds** (read from `bin/hos-cron:374-427` and `audit_log.py`):

- **H-1.** Distinct records have distinct paths. The path is `ts` + slug + `sha256(bytes)[:12]`, so
  two writers can only share a path if their bytes are byte-identical, and then the "conflict" is
  harmless.
  - A 48-bit hash within the same second and slug has a negligible collision probability.
  - `write_event` raises on an actual collision rather than overwriting.
- **H-2.** The push is non-force (`:421`). When two clones race, the loser gets a non-fast-forward
  rejection. It cannot clobber the winner's commit.
- **H-3.** The loser's files stay on its local disk, since nothing deletes them, and the next cycle
  re-sends them. Nothing is lost.
- **H-4.** The Worker and Overseer are separate clones (separate directories and `.git`). They share
  no worktree metadata, index or lock. Each sync runs under its own `hos-cron` overlap lock.

**Where it does not hold, and what closes each gap:**

| # | Gap in the current code | Consequence | Closed by |
|---|---|---|---|
| C-1 | No retry within a cycle | The losing clone waits a whole cycle; this affects liveness only | §6.2 step 7: 3 attempts, rebuilt on the new tip, with jitter |
| C-2 | Skip is existence-only (`[[ -e "$_wt/$_f" ]]`), not content equality | Valid only for content-addressed names. For TD-VF-5's 441 hand-named files, a same-path / different-content pair would be **silently skipped forever** (verified 0 instances today) | §6.2 step 4: blob-id comparison. A mismatch becomes a reported `conflict`, not a skip. |
| C-3 | `ls-remote` failure (transient) → base `origin/main` | Safe today, because H-2 rejects the push. But if the branch is ever deleted, it is **recreated from `main`**, carrying framework source into the audit ref. | §6.2 step 3: never fall back. Root commit on genuine absence (TD-D8). |
| C-4 | Fetch failure `return 0`; push stderr `2>/dev/null` | Sync failures leave no trace; #1517 has nothing to watch | §6.1 exit codes, §6.3 `audit-sync-failed` event, stderr passed through |
| C-5 | `write_event` creates the final name before writing its bytes (`open("xb")`) | A sync (or a concurrent reader) in the **same clone** can copy an empty or partial file. It is then permanently on the branch (append-only), and the full local version becomes a C-2 conflict. The window is small but real under overlapping processes, the #1616 class. | §3.2 link-publish; §6.2 step 2 refuses malformed files |

**Under the new call pattern specifically:**

- **More writers per clone.** Doing-scripts (§9) now write at more points, including inside agent
  sessions (`pr_review.sh`, `post_comment.sh`). H-1 is unchanged. C-5 becomes more likely, which is
  why §3.2 is part of slice S1 and not deferred.
- **A third pusher** (the Human clone, ESC-4). H-1 through H-4 are unchanged. The chance of a
  contended push grows linearly with the number of pushers. C-1's bounded retry absorbs it.
- **Branch reads are informational only (iteration 2).** Decision-bearing reads stay local-only
  (TD-D4 as revised), so sync timing cannot change any skip/proceed answer. Only the generic `query`
  sees other clones' records, and it is stale up to the last fetch unless `--refresh` is passed.
- **The worktree checkout is gone.** `git worktree add` of the full base tree (32,214 files, and
  growing) on every cycle is replaced by plumbing over a temp index. This removes TMPDIR scratch
  directories and `worktree prune` interactions. It also removes the only step whose cost grew with
  the size of the trail.
- **Shallow repositories** (TD-VF-13). `fetch`, `read-tree`, `commit-tree -p <fetched tip>` and a
  non-force push all work from a shallow repository, as long as the server has the parent. Test
  T2.13 pins this.

---

## 8. Segregation — R4 made mechanical

### 8.1 `.gitignore` on `main`

- Add the line `audit/log/`.
- **Effect on untracked records:** new and untracked records no longer appear in `git status`. This
  fixes #1803's noise, and it stops `hos_repo_sync.sh:137` from treating every clone as dirty
  (TD-VF-8).
- **Effect on staging:** `git add -A` can no longer stage records. That closes the PR #1582 accident
  (TD-VF-7).
- **What it does not do:** it has no effect on the 7,927 records `main` already tracks. Those are
  ESC-1.
- The rest of `audit/` (`audit/*.md`, `escalations/`, `panel-runs/`) stays committed and
  un-ignored.

### 8.2 CI gate `audit_segregation` (in the already-required `oversight-gate-repo-scoped` job)

- **Wiring.** Add `audit_segregation` to the gate loop in `.github/workflows/oversight-gates.yml:306-315`.
  That job's context `oversight-gate-repo-scoped` is already required
  (`scripts/framework/setup_branch_protection.sh:178`), so **no branch-protection change is needed**.
- **Logic** lives in `audit_segregation_logic.py` and is pure given its inputs. The shell layer
  gathers the inputs with git. The gate **fails** if either condition holds:
  - **(a)** the PR range `origin/<base>...HEAD` **adds or modifies** any path with the prefix
    `audit/log/`, according to `git diff --name-status --no-renames`. Deletions are allowed, which
    is what ESC-1 needs.
  - **(b)** any commit in `git rev-list origin/<base>..HEAD` is reachable from
    `refs/remotes/origin/audit-log` but not from `origin/<base>`. Checked newest-first with
    `merge-base --is-ancestor`, failing fast. A merge of `audit-log` contains thousands of sync
    commits, so the first check hits.
- **Absent `audit-log` ref:** if `git fetch origin audit-log` also finds nothing, condition (b)
  **raises no violation**, because there is no `audit-log` commit that could be in the PR. **An
  absent `audit-log` ref therefore passes (b).** The gate prints the disclosure line `audit-log ref
  absent — condition (b) not evaluated`. Condition (a) is evaluated as normal. T3.4 pins this.
- **Output:** a one-line PASS/FAIL per condition. Exit 0 on pass, 1 on fail, 2 on usage.
- **`pre_pr_stale_check.py`.** `check_audit_log_not_committed` additionally flags any added or
  modified path with the prefix `audit/log/`. This gives the worker an early warning before CI. The
  stale docstring claims (TD-VF-10) are corrected. The dead `audit/overnight-loop-log.md` entry
  stays, because it is harmless and removing it is out of scope.

### 8.3 Contract

`contract/OVERSIGHT-CONTRACT.md`:

- **§1:** `audit/log/**` is **not** on the default branch. It lives on the `audit-log` ref, which is
  written only by `bootstrap/audit_sync.sh` and never merged.
- **§6a intro:** replace the retired `oversight-log.jsonl` wording with the per-entry record grammar
  and the read entry point.
- **Catalog:** add rows for the new events in §9.

In the HOS repo these changes land in S3. Whether consumers receive the same filesystem change is
ESC-3.

---

## 9. Call-site inventory — which doing-scripts write what, and where

**"Required" means AD-10 halt-on-failure: a write failure must stop finalization. "Best-effort"
means a failure never changes the script's outcome but always prints the WARN line.** §10 gives the
policy.

### 9.1 New forced events

| Script | Insertion point (current lines) | Event · key fields | Mode |
|---|---|---|---|
| `scripts/run_panel.sh` | Before `exit 0` at `:522`, in the LOW-not-sampled skip | `panel-skipped` · `pr, risk, sampled:false` | best-effort |
| `scripts/run_panel.sh` | After `panel-release.json` is written (`:1049`), before `exit 0` (`:1052`) | `panel-run` · `mode:"release", base_sha, head_sha, effective_tier, findings_total, tier1` | best-effort |
| `scripts/run_panel.sh` | After `panel-verdict.json` (`:1059`), before the escalation branch (`:1066`). Non-dry-run only; a dry run records nothing because it attests nothing. | `panel-run` · `mode:"pr", pr, head_sha, risk, findings_total, tier1, new_blocking, suppressed, arbiter_salvaged, escalate:bool` | best-effort |
| `scripts/run_second_review.sh` | Both skipped-sentinel exits (`:348`, `:375`) | `second-review-run` · `step, verdict:"skipped", reason` | best-effort |
| `scripts/run_second_review.sh` | Right after `FINAL_VERDICT` is computed (`:1007`), before the fail-closed branches, so every terminal verdict is recorded | `second-review-run` · `step, verdict, reviewed_range, new_blocking, outfile` | best-effort |
| `scripts/oversight/run_validators.sh` | CRITICAL tool-preflight path, before `exit 1` (`:181`) | `validators-run` · `tier:"CRITICAL", fail_closed:true, reason:"tool_preflight"` | best-effort |
| `scripts/oversight/run_validators.sh` | After the aggregate block ends (`:510`), and again after the committed artifact (`:550`) when `--step` is given (with `artifact_path`) | `validators-run` · `composite_score, tier, tier_floor?, step?, head_sha?` | best-effort |
| `bootstrap/submit_pr.sh` | Update mode: after a successful push, before `echo "$PR_HTML_URL"` (`:278-280`). Open mode: after `gh pr create` succeeds (`:287`), before `echo "$PR_URL"` | `pr-opened` / `pr-updated` · `pr, head_branch, base, head_sha` (from `git rev-parse refs/heads/$HEAD`) | best-effort (the PR is the durable artifact) |
| `bootstrap/post_comment.sh` | After `gh issue comment` succeeds (`:103-106`), before `echo` (`:109`) | `comment-posted` · `number, kind, head_sha?, body_sha256, url, app_role` | **required only when `--kind` is passed** (→ exit **4**). Without `--kind`: best-effort, and every exit code is unchanged (see below). |
| `scripts/automation/pr_review_cli.py` `main` | After the handler returns (`:1228`) with `exit_code == 0` **and** `payload.posted is True`. A verified no-op (`skipped: true`) records nothing, since the prior event exists. | `submit-verdict` → `pr-review` · `pr, head_sha, verdict_event, tier, review_id`. `request-reviewer` → `reviewer-requested` · `pr, tier, reviewer` | **required** → exit **4** (see below) |

**`post_comment.sh` gains two optional flags:**

- `--kind <slug>` must match `^[a-z0-9][a-z0-9-]{0,47}$`.
- `--head-sha <40-hex>`.

Both are literal. Neither changes what is posted.

**Exit-code rule (F2, iteration 2) — the new code is opt-in, so no existing caller changes
meaning.**

| Invocation | Audit write | Exit codes |
|---|---|---|
| **Without `--kind`** (every existing caller) | Best-effort `comment-posted` with `kind:"unspecified"`. A failure prints the WARN line. | **Byte-unchanged:** 0 = posted; `err` paths exit 1 as today. **Never 4.** |
| **With `--kind`** (only new idempotency-keyed prose, §9.3) | **Required.** | 0 = posted and recorded. **4 = posted, but NOT recorded**: stdout still carries the URL. The caller must not retry the post, must not finalize, and must report. |

The rationale: `comment-posted` records only matter to the `comment-posted` named question, which
filters on `kind`. A record without a kind can never answer it, so making that write required would
add a failure mode with no idempotency benefit.

**Every existing caller, and what changes for it** (TD-VF-17):

| Caller | Passes `--kind` after this issue? | Handling change | Slice |
|---|---|---|---|
| `scripts/run_release_panel.sh:186-189` (script; `if ! bash "$POST_COMMENT_SH" …; then … exit 5`) | **No** | **None.** Without `--kind`, exit 4 is unreachable, so its `post-failed` mapping stays correct. `tests/oversight/test_release_panel_shell.py` must pass **unmodified**. That test is the regression guard for F2. | — (unchanged) |
| `worker.md:129` (script table), `:286, :343, :658, :709, :878, :882, :885, :887` (narrative / results / error comments) | No | None | — |
| `worker.md:833` (`<!-- hos-ng3b-awaiting -->` marker comment, which already has an ad hoc "check for" precheck) | **Yes:** `--kind ng3b-awaiting` | The ad hoc check becomes `bash bootstrap/audit.sh comment-posted --app worker --number <n> --kind ng3b-awaiting`. Prose adds: *"exit 4 → the comment is posted; do not re-post; stop and report."* | S6 (top-level session) |
| `overseer.md:726` (script table), `:803` (narrative comment) | Only on the re-postable-comment path §9.3 names | The same exit-4 sentence is added wherever `--kind` is introduced. The table row documents `--kind`/`--head-sha` and exit 4. | S6 (top-level session) |
| `tests/automation/test_post_comment.py`, `test_comment_format_check.py`, `tests/framework/test_overseer_verdict_artifact.py` | n/a | Existing cases must pass **unmodified**, since none passes `--kind`. New cases are added for `--kind` (T5.3). | S6 |

**`bootstrap/submit_pr.sh` gets no new exit code.** Its `pr-opened`/`pr-updated` and
`stale-base-merged` writes are best-effort (§10), so its exit contract is byte-unchanged. Its callers
(`worker.md:130, :383, :435`, `worker-cron-prompt.md:136`, `tests/automation/test_submit_pr.py`)
need no handling change. `test_submit_pr.py` must pass unmodified, apart from added event
assertions.

**`pr_review.sh` exit 4** (required on every posted mutation) means *"the mutation was performed,
and its audit record was NOT written."*

- The JSON record keeps the posted payload and adds `audit_recorded: false`.
- The caller must not retry, and must halt finalization.
- Its only caller is `overseer.md`'s step-6 prose ("Ordering within step 6", `:590-592`). S5 changes
  that prose to handle exit 4 in the same PR. No script calls `pr_review.sh`; checked by the same
  grep as TD-VF-17.
- This extends #1657's exit contract (TD-O5).

### 9.2 Existing writers migrated to the new API (behavior preserved; stderr no longer suppressed)

| Site | Change |
|---|---|
| `bin/hos-cron:362-365` `_audit` | Drop `2>/dev/null` (§6.3). The `cycle_log` role comes from `HOS_CYCLE_ROLE` (§3.4). |
| `bootstrap/submit_pr.sh:79-95` | Replace the hand-built `printf` JSON with `audit_append --writer bootstrap/submit_pr.sh --event stale-base-merged --str branch=… --str base=… --int behind_count=…`. Best-effort. |
| `scripts/oversight/run_with_retry.sh:119` | Replace `2>&1 \|\| true` with best-effort `audit_append` (the WARN line reaches stderr). |
| `bootstrap/lib/branch_ownership.sh:281-301`, `run_redteam_sample.sh:307-309`, Python writers in TD-VF-2 | **Unchanged in this issue.** They already use the single serializer. Migrating them is churn with no contract gain, and it is listed as optional cleanup. |

### 9.3 Agent prose migrated

| Site | Today | After |
|---|---|---|
| `overseer.md:154` | `source …; audit_read_stream \| grep \| grep` | `bash bootstrap/audit.sh decision-fired --app overseer --pr <n> --event human-authorized-merge` |
| `overseer.md:155, :163` | `audit_write_event '{…}'` | `bash bootstrap/audit.sh record --app overseer --event <E> --json-file <path>`, where the file holds `{"pr": <n>, "merged_by": "<login>"}`. The file form is required because bot logins contain `[` and `]`, which fall outside the literal-argv class (§5). |
| `overseer.md:161`, `overseer-cron-prompt.md:38` | source + grep | `… decision-fired --app overseer --pr <n> --event pr-merged-without-review` |
| `overseer.md:181-182` | source + triple grep | `… release-cleared --app overseer --release-file <path>`. The file holds the milestone title. Titles contain spaces and an em dash, so they never go on argv (F4). |
| `overseer.md:214` | `audit_write_event` | `… record --app overseer --event release-gate-validation --json-file <path>` |
| `overseer.md:317, :492, :692` | `audit_write_event` / "log this" | `… record --event human-approval-detected` / `codeowners-gate-evaluated` / `human-required` |
| `overseer.md:590-592` "Ordering within step 6" | The agent appends the verdict audit event after `submit-verdict` | The **wrapper** writes `pr-review`. The agent's audit step is removed. Exit 4 = halt and do not finalize. |
| `overseer.md` #849 comment prechecks | ad hoc | Before a re-postable comment: `… comment-posted --app overseer --number <n> --kind <k> [--head-sha <s>]`. Post with the same `--kind`. |
| `worker.md:894-905` | Append to retired `audit/oversight-log.jsonl` | `bash bootstrap/audit.sh record --app worker --event ng3b-violation-attempt --json-file <path>` |

---

## 10. Failure semantics — reconciled with ADR-1357 AD-10

| Class | Examples | On write failure | Why |
|---|---|---|---|
| **Disposition / mutation evidence** (AD-10 wrappers; idempotency-keyed events whose absence causes a repeat action) | `pr-bounced` (existing, `record_pr_bounce` raises before finalize: unchanged), `pr-review`, `reviewer-requested`, `comment-posted` **when `--kind` is given** (without `--kind` it is best-effort; §9.1), every `record` event, #1357 slice-4 events | **Required.** The mutation has already happened (post → confirm). The script returns exit 4, or raises in L1. The caller does not finalize and does not retry the mutation. | This is exactly AD-10's order: post → confirm → **append** → finalize, halting if the append fails. A missing record here causes the #849 duplicate on the next cycle. |
| **Control-ran telemetry** | `panel-run`, `panel-skipped`, `second-review-run`, `validators-run`, `pr-opened`, `stale-base-merged`, `validator-failure`, `cycle-*` | **Best-effort.** The script's exit code and outcome are unchanged. One WARN line goes to stderr. | The control's primary artifact (the PR comment, `$OUTFILE`, `summary.json`, the PR) is already durable. Failing a completed review because local disk was full would add a failure mode without adding evidence. **Routed as TD-O1**, since the architect owns AD-10's scope. |
| **Sync** | `audit_sync.sh` | Never fails a cycle. Nonzero → WARN + `audit-sync-failed` event. | Records are retained locally, so a failed push loses nothing (§7 H-3). |

Local writes fail only on disk, permission, validation or hash-collision errors. None of these is
network-dependent. R1's "no git operations at this layer" holds: `append_event` and `write_event`
never invoke git.

---

## 11. Backlog sweep

1. **Measured state:** §0.3. 8 records are genuinely unsynced across the three clones. Everything
   else is already on `audit-log`, byte-identical.
2. **Worker and Overseer are automatic.** Once S2 is on `main` and each clone fast-forwards, the next
   cycle's `audit_sync.sh` pushes the stragglers. No manual step.
3. **Human clone.** This takes either S8 (ESC-4: `hos-human` runs the sync at session start) or a
   one-time `bash bootstrap/audit_sync.sh` run by the human in their own terminal. That is a literal
   command the human-proxy session can hand over.
   - Note: the Human clone is also 164 commits behind with tracked modifications (§0.3). Its sync is
     unaffected, because the sync never touches the working tree or HEAD. It does need S2's scripts
     to be present, which means a pull.
4. **Verify.** In each clone, `bash bootstrap/audit_sync.sh --status` must report
   `missing_on_branch: 0`. The three JSON lines are recorded on #1538 as the sweep evidence.
5. **S3 lands `.gitignore`.** Untracked noise disappears. With step 4's evidence, **#1803 can close**
   (its records are preserved, not committed to `main`), and **#1095's backlog-recovery item** is
   superseded.
6. **Optional (ESC-1): remove the 7,927 `main`-tracked records.**
   - **Precondition:** a `--status`-equivalent check against `main`'s tree shows every one of them
     is on `audit-log` with an identical blob. The S7 PR body must include that output.
   - **History-loss constraint (revised in iteration 2).** Decision-bearing readers are now
     local-only (TD-D4 as revised). Pulling the deletion would remove those files from every clone's
     working tree, so the Worker clone's `step_range.sh` would lose its `step-head` history from
     before 2026-09-11.
   - **If ESC-1 is answered "remove", S7 must therefore include a one-time local restore.** For each
     removed path, it writes the blob from **`main`'s pre-removal tree** back into the working tree
     as an untracked, now-ignored file.
     - The blobs come from `main`'s history, not from `audit-log`: those files entered `main` through
       a merged PR, so their provenance is `main`'s, not a pushed branch's.
     - Local copies are thereby restored exactly as they were.
     - The restore runs in `hos-cron` before its fast-forward, which is `bin/**` and human-gated.
7. **Other registered projects** (`projects.conf`) reach step 2 automatically once they upgrade.
   Their `.gitignore` depends on ESC-3.

---

## 12. Sandbox allowlistability of every new entry point

Every agent-invoked command is a single invocation of a literal path with literal flags. None needs
`source`, a pipe, command substitution, a heredoc, a variable expansion, a loop or chaining.

| Entry point | Invoked by | Allowlist shape |
|---|---|---|
| `bash bootstrap/audit.sh <query\|pr-reviewed\|decision-fired\|comment-posted\|release-cleared\|record> --app <role> …` | agents | `Bash(bash bootstrap/audit.sh *)` |
| `bash scripts/oversight/check_pr_reviewed.sh <pr#> <head_sha>` | overseer (existing) | unchanged |
| `bash bootstrap/audit_sync.sh [--status\|--dry-run]` | `hos-cron`, `hos-human`, human | `Bash(bash bootstrap/audit_sync.sh *)` (humans; agents never need it) |
| `bash bootstrap/post_comment.sh … --kind <k> [--head-sha <s>]` | agents (existing entry) | unchanged |
| `python3 -m scripts.oversight.lib.audit_log append …` | **committed scripts only** | Intended for committed scripts only. **It is not access-controlled:** the policy grants `Bash(python3 *)`, and cron runs with `bypassPermissions` (TD-VF-16). Iteration 1's "not allowlisted" claim is withdrawn. Nothing decision-bearing depends on agents not calling it. §5.4 states the actual control. |

- **Quoting (F4, iteration 2).** Argv values are restricted to `^[A-Za-z0-9._:/@#+=-]{1,200}$`
  (§5): no spaces, no quotes, no brackets, no glob characters. So **no audit command ever contains a
  quoted token**, and the `'\''` escape problem cannot arise. Free text (titles, summaries, logins
  with `[bot]`, lists) is passed only through `--release-file` or `--json-file`, whose contents the
  caller writes with a file tool. The CLI rejects an out-of-class argv value with exit 2 and a
  message naming the file-argument alternative.
- **Prose test (T5.4)** scans `overseer.md`, `worker.md` and both cron prompts. Every audit
  invocation must match
  `^bash bootstrap/audit\.sh [a-z-]+ --app (worker|overseer|human)( --[a-z-]+( [A-Za-z0-9._:/@#+=<>-]+)?)*$`.
  In prose, `<n>`-style placeholders are allowed by the `<>` in that class. The class has no quote
  characters. The test also fails if prose passes `query` output into any skip/proceed decision: a
  line containing `audit.sh query` together with `skip`, `already` or `do not` fails.
  The prose must contain zero occurrences of `audit_read_stream`, `audit_write_event` and
  `source scripts/oversight/lib/audit_log.sh`.

---

## 13. Startup-gap recovery, and affected sign-offs

**Should this have been settled before code was written against it?** Yes, in two places.

- **#888 (per-entry records)** defined the write grammar but no cross-clone read or sync contract.
  This design fills that gap.
- **#1657 (`pr_review.sh`)** shipped a mutation wrapper with no AD-10 audit event (TD-VF-12). A
  `startup-artifact-gap` should be opened or annotated. I am **not** filing it, per the task's
  no-GitHub-writes instruction; the parent session should.

### 13.1 Sign-offs that stand

- `audit_log.py`'s serializer and grammar: unchanged.
- `record_pr_bounce`: unchanged.
- `merge_authority.py` apart from the one `bounce_count` body (AD-10 pre-authorized it).
- `submit_pr.sh`'s push and create logic.
- Everything in #1357 slice 1 except as noted below.

### 13.2 Sign-offs flagged for re-review, with the reason

| Component (prior approval) | What changes under it | Re-review by |
|---|---|---|
| ~~`read_stream` consumers~~ (`step_range.sh`, `changeset.sh`, `audit_conditional_proceed.sh`) | **Iteration 2: no longer changed.** `read_stream` stays local-only (TD-D4 as revised). Their TD-220/#370 sign-offs **stand**. | — |
| `merge_authority.bounce_count` (#1357 slice 1 sign-offs) | Body swapped to `count_events(sources=("local",))`, with identical semantics. The prior sign-offs stand. The row is kept only because the file changes. | `code-reviewer` in S1; `test_bounce_gate.py` unmodified |
| `check_pr_reviewed.sh` (#1524) | Implementation replaced; output contract preserved; still local-only. **Its answer narrows:** records lacking the `pr_review_cli` provenance, other than legacy ones, are no longer counted (§5.2, F1). | `code-reviewer` + `security-reviewer` in S4; its test unmodified |
| `post_comment.sh` exit contract (#1155; its only script caller is `run_release_panel.sh`, ADR-1340) | **Opt-in** exit 4 with `--kind`. Without `--kind`, the contract is byte-unchanged (F2). ADR-1340's `run_release_panel.sh` sign-off stands, because it never passes `--kind`. `test_release_panel_shell.py` unmodified is the proof. | `code-reviewer` in S6; architect (TD-O5, extended) |
| `pr_review.sh` exit contract (#1657) | Exit 4 added; the agent's audit step moves into the wrapper | `code-reviewer` + `security-reviewer` in S5; architect (TD-O5) |
| `overseer.md` halt-on-failure ordering (SPEC-378 R3.3/R3.4) | The audit-append step for verdicts moves into the wrapper | S5 prose review (human-gated protected surface) |

---

## 14. Open items routed to the architect (TD-O)

- **TD-O1 — best-effort vs required per class (§10).** I classified control-ran telemetry as
  best-effort. AD-10 says "every wrapper records that it ran". My reading is that AD-10 binds the
  merge-authority surface, not `run_panel` or `run_second_review`. Confirm, or rule them required.
- **TD-O2 — the secret pattern is now used twice.** `audit_log.py` needs the token regex that
  `pr_review_cli.py:98` owns. The options are:
  - (a) promote it to a shared constant module that both import (touches `pr_review_cli.py`, one
    line); or
  - (b) keep two copies plus a drift test asserting identity.

  I recommend (a) in S1. Duplicated authority is the #1135 class.
- **TD-O3 — the `pr-reviewed` event set.** Should it absorb the improvised historical names
  (`pr-reviewed`, `pr-review-skipped-idempotent`, `idempotent-skip-prNNNN`, …; TD-VF-6)? Widening
  suppresses more duplicate reviews, but it also trusts improvised semantics. My recommendation is
  no: keep today's set. §5.3's closed enum stops new drift.
- **TD-O4 (rewritten in iteration 2) — please confirm that TD-D4's source policy satisfies AD-20.**
  Iteration 1 made `read_stream` a union, and F1 showed that made forged cross-clone records live.
  The revision keeps one reader function with a **required, per-call-site, code-frozen** `sources`
  policy: decision-bearing reads are local-only, and the informational `query` is a union. My claim
  is that this is still one authority, with a documented policy per call site, not "two answers". It
  is the architect's to accept or reject.
- **TD-O5 (extended in iteration 2) — new exit codes on shipped wrappers.** `pr_review.sh` exit 4 is
  unconditional on a posted mutation whose record failed. `post_comment.sh` exit 4 is opt-in via
  `--kind`, which is what F2 requires. Both extend approved contracts (#1657, #1155).
- **TD-O8 (new in iteration 2) — the provenance filter's trust in legacy records.** Named questions
  accept local records **without** a `writer` key (`accept_legacy`), so today's answers for existing
  history are preserved. A same-clone process could forge a writer-less record. That is no worse
  than today, where every local record is trusted, but it leaves a permanent legacy door open. The
  alternative is a cutoff: accept legacy only if the record's `timestamp` is before the S4 merge
  instant, pinned as a constant. That closes the door for new writes at the cost of one constant.
  I recommend the cutoff; the architect decides.
- **TD-O6 — exposing `trail_present` in `merge_authority_cli bounce-count`.** Available after S1.
  Owned by #1357 slice 4 (TD-1357 §14.6).
- **TD-O7 — ADR-035 retirement** (`audit_predicate.py`, `audit_allowlist.txt`): a follow-up issue,
  or a slice here?

---

## 15. Human decisions (ESC) — not guessed

- **ESC-1 — Remove the 7,927 audit records `main` tracks (TD-VF-7)?**
  - It is one mechanical `git rm -r --cached audit/log` commit, so it **exceeds the ≤15-file slice
    cap** and needs an explicit waiver.
  - Pulling it deletes those working-tree files in every clone. Because decision-bearing reads are
    now local-only (F1), this needs the restore step in §11 step 6, which touches `bin/**`.
  - The alternative is to leave them frozen on `main`. That is harmless, but `main` then holds a
    stale partial trail. `.gitignore` does not affect tracked files, so they stay tracked.
  - *Recommendation (changed in iteration 2): **leave them frozen.** Removal now costs a waiver plus
    a `bin/**` restore step, in exchange for a tidier `main`. If a human prefers removal, S7 carries
    the restore.*
- **ESC-2 — Add a repository ruleset on `audit-log`: block force-push and block deletion.** It would
  require no PR and no reviews, so it changes no approval gate. Today the branch is unprotected, so
  any token with push access can rewrite the committed audit history. This is a repo-admin action.
  *Recommendation: yes.*
- **ESC-3 — Consumer rollout.** `hos-cron` ships to consumers, so their clones already push to their
  own `audit-log`. The question is whether consumers also get the §8 filesystem change in this
  release. That covers `hos_install.sh` adding `audit/log/` to `.gitignore`, and fixing
  `ensure_not_ignored "audit/"` (`:751`) and the substring check at `:2150`, both of which would
  **falsely warn** on an `audit/log/` line. It also covers contract §1 describing consumer repos.
  That is a consumer-facing contract change.
  *Recommendation: yes, as S9, in the same milestone.*
- **ESC-4 — Should `bin/hos-human` run `bootstrap/audit_sync.sh` at session start?** It would push to
  `audit-log` under the existing Human App identity, as a launcher side effect: no source edit, no PR.
  Without it, Human-clone records are never synced (TD-VF-9).
  *Recommendation: yes (S8).*
- **ESC-5 — The existing `audit-log` history** carries 666 framework-source files and `main` history
  up to 2026-08-09 (TD-VF-5).
  - (a) Leave it as it is. This is my recommendation: a rewrite needs a force-push, which
    contradicts ESC-2 and destroys the evidence chain.
  - (b) Re-root it as an orphan once, with human authorization.

  Either way, only *new* branch creations become root commits (TD-D8).
- **ESC-6 (new in iteration 2, from F1) — Cross-role record forgery cannot be made unforgeable
  inside one OS user.** §5.4 shows what the design closes:
  - cross-role forgery through `audit.sh record --app …`;
  - suppression through attestations;
  - event-name drift.

  It cannot stop a process that writes directly into another role's clone. Worker and overseer run
  as one OS user, with `bypassPermissions` and no generated sandbox policy (TD-VF-16), so envelope
  fields and environment variables are all forgeable. Such a process could equally edit that clone's
  `overseer.md`. The exposure predates this issue. Iteration 1's union reader would have widened it,
  and iteration 2 does not. Options for a real guarantee, none of which this issue can decide:
  - **(a)** Run each role as a **separate OS user** with its clone and App key readable only by that
    user. Then the clone boundary becomes OS-enforced, and §5.2's local-only reads become an
    unforgeable cross-role guarantee.
  - **(b)** Ship the #1146/#1542 per-role sandbox policy with `allowWrite` limited to the role's own
    clone and `denyRead` on the other roles' App keys. The effect is the same as (a), provided cron
    stops bypassing the sandbox.
  - **(c)** Accept the residual. Treat the named questions as corroborating only, which is how
    `overseer-cron-prompt.md:58` already frames `check_pr_reviewed.sh`, and keep every authoritative
    skip decision on GitHub-side state (PR reviews and comments, read under the role's own token).

  *Recommendation: (c) now, and it is already the case for `pr-reviewed`. Take (b) as the real fix
  through #1146/#1542. Record the ruling on #1538 so S4's prose states which of the named questions
  may be authoritative.*

---

## 16. Tests (Python for all decision logic; `tests/<area>/test_*.py`; runnable via `scripts/framework/run_tests_inner_loop.sh`)

Git fixtures build a bare "remote" and one or two clones under `tmp_path`. They follow the existing
helpers in `tests/automation/test_hos_cron.py:3770-3930`, which S2 moves into
`tests/oversight/test_audit_sync.py`.

### 16.1 S1 — `tests/oversight/test_audit_log.py` (extended) and `tests/oversight/test_audit_query.py` (new)

- **T1.1 — envelope.** Covers:
  - envelope fields are present;
  - a reserved key in `fields` → `ValueError`;
  - `role` precedence (explicit > `HOS_CYCLE_ROLE` > `unknown`);
  - `cycle_id` is omitted when unset or invalid;
  - `writer` is required.
- **T1.2 — typed CLI.** `--str/--int/--bool/--json-file`. The case `--str head_sha=1234567` must stay
  a string. A duplicate key is exit 2.
- **T1.3 — atomic publish.**
  - A crash after the temp write leaves no final file, and the reader and sync ignore the dot-temp
    file.
  - Two threads writing identical bytes → one file, same relpath.
  - A forced different-bytes collision (via monkeypatched digest) → `RuntimeError`.
- **T1.4 — secret refusal.** A token-shaped value at any depth → `ValueError`, and nothing is
  written.
- **T1.5 — size cap.** `canonical_bytes` over 64 KiB → `ValueError`.
- **T1.6 — required vs best-effort.** Test against a read-only `audit/log/`:
  - `required=False` returns `None` and emits exactly one WARN line on stderr;
  - `required=True` raises;
  - CLI `--required` → exit 5, and without it → exit 0.
- **T1.7 — union (only via `query_events(sources=("local","branch"))`).**
  - Local-only, branch-only and both-identical cases: dedup gives `source: "both"`.
  - The both-different case: two records and `conflicts == 1`.
- **T1.7b (iteration 2) — `read_stream` is unchanged.** Given a fixture repo whose
  `origin/audit-log` holds extra records, `read_stream` output is byte-identical to its output on the
  same local tree without the ref. The existing `test_audit_log.py` cases pass unmodified.
- **T1.7c (iteration 2) — source policy is pinned.** A test enumerates every `query_events(` and
  `count_events(` call in `scripts/` by AST and asserts its `sources` literal against a pinned
  table. A call with no `sources` argument fails. Named questions, `bounce_count` and
  `check_pr_reviewed` must be `("local",)`.
- **T1.7d (iteration 2) — provenance filter.** Covers:
  - a record with the right event but the wrong `role` is excluded and counted in
    `provenance_excluded`;
  - the wrong `writer` is likewise excluded;
  - a writer-less legacy record from local is counted;
  - a writer-less record from the branch source is excluded.
- **T1.8 — branch-source presence.** Absent in each case with its reason:
  - a root that is not a git top-level (including a temp dir nested in a repo);
  - no `origin/audit-log` ref.
- **T1.9 — filters.**
  - event OR; field AND;
  - canonical string-form typing (`pr=12` matches int `12` and str `"12"`, and never a list);
  - `since`/`until` using the `ts` fallback;
  - `untimed_excluded`.
- **T1.10 — malformed record.** In either source → `ValueError` naming source and relpath.
- **T1.11 — `trail_present`.** False with no directory and no ref; true otherwise.
- **T1.12 — `cycle_log` role.** Taken from `HOS_CYCLE_ROLE` (VF-1). The existing
  `tests/automation/test_cycle_log.py` stays green.
- **T1.13 — `bounce_count`.** `tests/automation/test_bounce_gate.py` **unmodified and green**. A new
  case confirms that a branch-only `pr-bounced` record is counted.
- **T1.14 — Bash/Python parity.** `audit_append` from Bash produces the same bytes as
  `append_event`, given a pinned timestamp and environment.
- **T1.15 — performance.** On a synthetic 100k-record branch fixture, `query_events` finishes in
  under 5 s. Marked `slow`, and it runs in the inner loop only if the inner loop already runs slow
  tests; otherwise it runs in `tests.yml`.

### 16.2 S2 — `tests/oversight/test_audit_sync.py` (new) and `tests/automation/test_hos_cron.py` (modified)

- **T2.1 — push to `audit-log`.** New records reach `audit-log`. The live checkout's HEAD, index
  file bytes, `git status --porcelain=v2` and branch are all byte-identical before and after.
- **T2.2 — nothing to sync.** No commit, exit 0, `outcome: nothing_to_sync`.
- **T2.3 — absent remote branch.** The new commit is a root commit (no parents), and its tree is
  exactly `audit/log/**`.
- **T2.4 — the race.** Clones A and B both fetch. A pushes. B's first push is rejected, B retries on
  A's tip, and it succeeds. The union of both record sets is on the branch, history is linear, and
  `attempts == 2`.
- **T2.5 — contention exhaustion.** Simulated with a pre-receive hook that rejects N times → exit 4.
  Local files are untouched. The next run succeeds.
- **T2.6 — conflict.** Same path, different bytes → not overwritten, reported, exit 3. The other
  records are still pushed.
- **T2.7 — rejects and name conformance.**
  - A malformed local file → rejected, not pushed, exit 3.
  - A grammar-named file with the wrong hash → pushed and counted in `nonconforming_names`.
- **T2.8 — fetch failure.** An invalid remote URL → exit 5. No commit is created, and there is
  **no** fallback to `main`.
- **T2.9 — housekeeping.**
  - Dot-temp files are ignored.
  - Temp indexes older than 1 hour are cleaned.
  - Local records are never deleted: the file set is identical before and after in every test.
- **T2.10 — `--status`.** Correct counts and `oldest_missing_ts` with the remote URL made invalid,
  which proves it is offline.
- **T2.11 — `--dry-run`.** Creates no objects on the remote and no push.
- **T2.12 — remote-tracking ref.** `refs/remotes/origin/audit-log` equals the pushed commit after
  success.
- **T2.13 — shallow source clone.** A `--depth 1` clone syncs successfully.
- **T2.14 — static check.** No `--force`, no `2>/dev/null`, and no `worktree` in `audit_sync.py` or
  `audit_sync.sh`.
- **TW-2 — `hos-cron` wiring.**
  - `_sync_audit_logs` is absent.
  - `bootstrap/audit_sync.sh` is invoked exactly once, after the cycle.
  - A nonzero exit produces a WARN line and an `audit-sync-failed` event, with the cycle exit
    unchanged.
  - `_audit` has no `2>/dev/null`.
  - The re-mint happens when more than 45 minutes have elapsed (clock injected).

### 16.3 S3 — `tests/oversight/test_audit_segregation.py` (new)

- **T3.1** — a PR adding `audit/log/x.json` fails (a).
- **T3.2** — a PR that only deletes `audit/log/**` passes.
- **T3.3** — a PR containing a merge of `audit-log` fails (b).
- **T3.4** — an absent `audit-log` ref: condition (b) raises no violation. The gate **passes**
  when (a) is clean, and it prints the disclosure line. It still **fails** if (a) is violated.
- **T3.5** — ordinary PRs pass.
- **T3.6** — `git check-ignore` is true for `audit/log/2026/09/x.json` and false for
  `audit/2026-06-14-self-3p-eval.md`.
- **T3.7** — `tests/automation/test_pre_pr_stale_check.py` gains the `audit/log/` prefix case.
- **T3.8** — `tests/framework/test_branch_protection_contexts.py` stays green. No context changed.

### 16.4 S4 — `tests/oversight/test_audit_query_cli.py` (new) and `tests/oversight/test_audit_wrapper.py` (new)

- **T4.1 — flag rules.**
  - `--app` required, closed role set.
  - `--root`, `--source`, `--repo-root` and `--config` → exit 2 on every subcommand.
  - An unknown subcommand → exit 2.
- **T4.2 — named-question truth tables.** Includes `headSha` legacy matching for `pr-reviewed` and
  `decision-fired`, and `E` outside the closed set → exit 2.
- **T4.2b (iteration 2) — the F1 regression test.** Two clones of one bare remote, W and O.
  1. In W, with `HOS_CYCLE_ROLE=worker`, run `audit.sh record --app overseer --event human-required
     --int pr=7 --str head_sha=abc` → exit 3 (`app_role_mismatch`).
  2. Repeat step 1 with `HOS_CYCLE_ROLE` forged to `overseer` → the write succeeds into **W's**
     local dir. W's sync pushes it. O fetches.
  3. In O, `audit.sh pr-reviewed --app overseer --pr 7 --head-sha abc` → `answer: false`. The same
     holds for `decision-fired`, and `check_pr_reviewed.sh 7 abc` → `already_reviewed: false`.
  4. In O, a record written into **O's** dir through `record --event human-required` is also not
     counted by `pr-reviewed`, and `provenance_excluded == 1`.
  5. `audit.sh query` in O **does** show the W record, with `source: "branch"` and
     `authoritative_for_suppression: false`.
- **T4.2c (iteration 2) — argv class (F4).** A value containing a space, `'`, `"`, `[`, `]` or `*`
  → exit 2, with the message naming `--json-file`/`--release-file`. `--release-file` containing an
  em-dash title with an apostrophe round-trips exactly.
- **T4.3 — `record` enum.**
  - Every attestable event succeeds, with `role = --app` and `writer` set.
  - `idempotent-skip` → exit 3 (removed in iteration 2).
  - `HOS_CYCLE_ROLE` unset with `--app` other than `human` → exit 3.
  - Every forced event → exit 3, and nothing is written.
  - The enum is pinned by a snapshot test.
- **T4.4 — `--refresh`** (on `query` only). Fetch failure → exit 5. `--refresh` on a named question
  → exit 2.
- **T4.5 — `check_pr_reviewed.sh`.** Its existing test file is green unmodified. The `[root]` form
  reads local only.
- **T4.6 — the L3 wrapper** passes stdout and the exit code through byte-identically, and writes
  nothing of its own to stdout.

### 16.5 S5 and S6 — doing-script events

- **T5.1 — each §9.1 insertion point.** The event is written exactly once with the listed fields on
  its path. Dry-run and skip paths write what §9.1 says and nothing more.
- **T5.2 — best-effort sites.** With a read-only `audit/log/`, the script's exit code and stdout are
  unchanged, and a WARN line appears on stderr.
- **T5.3 — required sites.** `pr_review_cli` with posted+audit failure → exit 4, and the JSON has
  `audit_recorded: false` with the posted payload intact. The same for `post_comment.sh --kind k`
  (with `gh` stubbed). A verified no-op writes nothing.
- **T5.3b (iteration 2, F2).** `post_comment.sh` **without `--kind`** and with a failing audit write
  → exit 0, the URL on stdout, one WARN line. Exit 4 is unreachable without `--kind`.
  `tests/oversight/test_release_panel_shell.py`, `tests/automation/test_post_comment.py`,
  `test_comment_format_check.py`, `test_overseer_verdict_artifact.py` and `test_submit_pr.py` pass
  **unmodified** (the last may add assertions only).
- **T5.4 — prose scan** (§12). Lands in **S4** as `tests/framework/test_audit_prose.py`, together
  with the first prose migration. S5 and S6 extend its fixtures.

---

## 17. PR slicing (each ≤15 files, ≤10 commits; in order)

| # | Slice | Files (approx.) | Protected surfaces touched | Depends on |
|---|---|---|---|---|
| **S1** | L1: `append_event`, atomic publish, `query_events`/`count_events` with required `sources` + provenance filter (`read_stream` unchanged), typed `append` CLI, `audit_append` facade, `cycle_log` role, the `bounce_count` one-function swap, the TD-O2 shared pattern | `audit_log.py`, `audit_log.sh`, `cycle_log.py`, `merge_authority.py`, (`pr_review_cli.py`, one line, if TD-O2 = a), `tests/oversight/test_audit_log.py`, `tests/oversight/test_audit_query.py`, `tests/automation/test_cycle_log.py`, `tests/automation/test_bounce_gate.py` (+1 case only) — **8–9** | none | — |
| **S2** | Standalone sync + `hos-cron` extraction, token re-mint, `_audit` stderr, false-comment removal | `scripts/oversight/lib/audit_sync.py`, `bootstrap/audit_sync.sh`, `bin/hos-cron`, `tests/oversight/test_audit_sync.py`, `tests/automation/test_hos_cron.py`, `SCRIPTS-INDEX.md`, ship-set list **if** the installer does not already glob `bootstrap/*.sh` (coder verifies with a `--local` install test), `.github/CODEOWNERS` (only if `regen_all.sh --check` produces a diff) — **6–8** | `bin/**`, `bootstrap/**` | S1 |
| **S3** | Segregation: `.gitignore`, CI gate, `pre_pr_stale_check`, contract §1/§6a, `DECISIONS.md` entry (supersedes ADR-035/#1157 and #1095's item; R4 recorded) | `.gitignore`, `scripts/oversight/gates/audit_segregation.sh`, `scripts/oversight/audit_segregation_logic.py`, `.github/workflows/oversight-gates.yml`, `scripts/automation/pre_pr_stale_check.py`, `contract/OVERSIGHT-CONTRACT.md`, `DECISIONS.md`, `tests/oversight/test_audit_segregation.py`, `tests/automation/test_pre_pr_stale_check.py`, `SCRIPTS-INDEX.md` — **10** | `scripts/oversight/gates/**`, `.github/workflows/**`, `contract/**` | S2 (so that ignored records are still synced) |
| **S4** | Agent-facing read/attest CLI + named questions + the `check_pr_reviewed.sh` shim + **read-precheck and `record` prose migration** (§9.3 rows 1–6 and 9) | `scripts/oversight/audit_query_cli.py`, `bootstrap/audit.sh`, `scripts/oversight/check_pr_reviewed.sh`, `tests/oversight/test_audit_query_cli.py`, `tests/oversight/test_audit_wrapper.py`, `tests/framework/test_audit_prose.py` (T5.4), `.claude/agents/overseer.md`, `.claude/agents/worker.md`, `bootstrap/overseer-cron-prompt.md`, `SCRIPTS-INDEX.md` — **10** | `bootstrap/**`, `.claude/agents/**` (**prose authored by the top-level session, not `coder`**) | S1. **Unblocks #1542 (AD-20).** |
| **S5** | Forced events, part A (verdict/review/panel): `pr_review_cli` + exit 4, `run_panel.sh`, `run_second_review.sh`, `overseer.md` "Ordering within step 6" | `pr_review_cli.py`, `bootstrap/pr_review.sh` (header exit table only), `scripts/run_panel.sh`, `scripts/run_second_review.sh`, 3 test files, `.claude/agents/overseer.md` — **8** | `bootstrap/**`, `.claude/agents/**` (top-level session) | S1, S4; TD-O5 ruled |
| **S6** | Forced events, part B: `run_validators.sh`, `submit_pr.sh` (`pr-opened`/`pr-updated` + `stale-base-merged` migration), `post_comment.sh` (`--kind`/`--head-sha`, `comment-posted`, exit 4), `run_with_retry.sh`, `comment-posted` precheck prose | 5 scripts, 3–4 test files, `.claude/agents/overseer.md`, `bootstrap/worker-cron-prompt.md` (if it posts re-postable comments) — **10–11** | `scripts/oversight/run_validators.sh`, `bootstrap/**`, `.claude/agents/**` (top-level session) | S1, S4 |
| **S7** | *(blocked on ESC-1)* Remove the `main`-tracked records | 7,927 deletions, one commit; needs a waiver | none (`audit/log/**` is not listed) | S1, S3; verified with `--status` |
| **S8** | *(blocked on ESC-4)* `hos-human` runs the sync at session start (best-effort, never blocks the session) | `bin/hos-human`, a test file — **2** | `bin/**` | S2 |
| **S9** | *(blocked on ESC-3)* Consumer install: `.gitignore` line, `ensure_not_ignored` exact-line fix, contract consumer wording | `bootstrap/hos_install.sh`, `contract/OVERSIGHT-CONTRACT.md`, install test — **3** | `bootstrap/**`, `contract/**` | S3 |

- **Sweep verification (§11, step 4)** is an operational step after S2 (and S8, or the human's manual
  run). It produces no PR, only evidence posted on #1538.
- **S4 and S5 ship in the same release (iteration 2).** Between them, `pr-reviewed` stops counting
  prose-written records before the forced `pr-review` producer exists (§5.2). Merge S5 immediately
  after S4, and do not cut a release between them.
- **S6 changes no existing `post_comment.sh` caller's handling** (F2 table, §9.1). It adds `--kind`
  only at `worker.md:833` and the overseer's re-postable-comment path, with exit-4 prose in the same
  PR.
- **Cross-issue sequencing:**
  - #1357 slice 4 mutation wrappers must land **after S1** and call `append_event(required=True)`.
  - #1542 slices that need audit reads block on **S4** (AD-20).
  - #1517 retargets onto `audit_sync.sh --status` and `audit-sync-failed` after **S2**.

---

## Human Review Required

**RISK:** HIGH. The design touches:

- the audit trail's integrity and location;
- `bin/hos-cron`'s end-of-cycle path;
- a required CI gate job;
- the consumer contract (via ESC-3);
- the exit contract of a merged mutation wrapper (#1657).

**CONFIDENCE:**

- **HIGH** on the inventory and on the concurrency analysis (§0, §7). Every writer, reader and gap
  was read in the tree or measured against the live ref and the three clones, not inferred.
- **MEDIUM** on the §10 best-effort classification (TD-O1) and on the source-policy argument
  (TD-O4). Both are routed.
- **HIGH** that §5.4 neither overclaims nor underclaims. The F1 scenario is closed. Same-OS-user
  forgery is not closable here, and ESC-6 says so.

**Change classification: `structural`.**

- The move of `audit/log/**` off `main` (R4) and the forced-side-effect model (R2) trace to human
  rulings already given.
- The structural elements not covered by a ruling are ESC-1 through ESC-5, and they are escalated,
  not decided.
- ESC-6 is new in iteration 2.
- The existing-contract changes (iteration 2) are:
  - the narrowed `check_pr_reviewed.sh` answer (F1);
  - `pr_review.sh` exit 4;
  - opt-in `post_comment.sh` exit 4 (F2).

  They are listed in §13.2 and routed as TD-O4, TD-O5 and TD-O8. Iteration 1's union `read_stream`
  is withdrawn, so the `step_range`/`changeset` sign-offs no longer need re-review.

**Nothing in S7–S9 may be built until its ESC is answered. Nothing may be built until the architect
approves.**

**Startup-gap:** §13. A `startup-artifact-gap` annotation is recommended for #1657 (TD-VF-12). It
has not been filed, per the task's no-GitHub-writes instruction.
