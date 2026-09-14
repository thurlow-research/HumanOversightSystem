# ADR-1340 — The release panel is a mode on the existing panel engine, and its R2 gate verifies a recomputed execution artifact transported by GitHub, never a committed stamp

**Status:** ACCEPTED FOR DESIGN — binds `technical-design`. **Two items are held for the human** (§6): ESC-1 (the shallow-clone remediation, which is an operational-obligation change and *already* degrades a live R2 suite), ESC-2 (out-of-band execution cost + who runs it). Everything else is **BINDING**.
**Date:** 2026-09-14
**Author:** architect
**Inputs:** pm-agent's requirements for #1340 (evidence base E1–E12, REQ-A1..A12 / REQ-C / REQ-D); the human's rulings on ESC-1..ESC-5 (2026-09-14); my own re-derivation against the working tree at `0b86aa52` (§0).
**Consumers:** `technical-design` (next), then `coder`.
**Source issues:** #1340 (this); siblings #1622, #1623, #1624, #1625 (re-homed guarantees), #1621; #682 (fail-closed reviewer), #978 (arbiter salvage), #314/SPEC-333 (panel logic in Python), #555 + ADR-1594 (committed-artifact precedent), #1155 (`post_comment.sh`), D41 (one invocation site).
**Explicitly does NOT re-litigate:** E1–E12 (pm-agent established them; §0 confirms the load-bearing ones), REQ-A1..A12 behaviour (fixed), or the REQ-B7/B8 removal (blocked on siblings, out of scope).

---

## 0. Verification — premises re-derived this session

### Confirming pm-agent

- **E1/E2 CONFIRMED.** `run_panel.sh` is PR-bound at `:214-219` (PR + `HEAD_SHA` via `gh pr view`), `:223` (ledger path), `:249-253` (run dir + `gh pr diff`), `:293-296` (author `AI-Risk:` trailer scan over `gh pr view --json commits`), `:656-658` (`post_thread` → `POST .../pulls/$PR/comments` with `commit_id="$HEAD_SHA"`), `:348-350` (SQC keyed on `HEAD_SHA`). The unanchorable-finding degradation at `:700-705` → `:735-737` is real and is, as pm-agent says, the seed of release mode.
- **E3/E4 CONFIRMED.** `run_review_chain.sh:288-292` skips the panel entirely without `--pr`; worker.md's R2 invokes it without `--pr`. No `.ai-local/panel/` exists. **The panel core has never executed in this repository.**
- **E8 CONFIRMED as to location** (`run_review_chain.sh:109-152`, `run_validators.sh:349`) — and **refuted as to behaviour in this repo**. See AF-1.
- **E10 CONFIRMED, and tighter than stated.** worker.md R1.9 check 3 (`:583-632`) walks anchor comments **matched by script path**, and R3 (`:658-670`) fixes the line format to `- <suite-script-path>: PASS|FAIL (exit <code>) at <UTC timestamp>`. A new suite must therefore present *one stable script path* — not a path plus mode flags that vary between runs.

### My own findings — these change the design

**AF-1 (CRITICAL — the mandated range derivation collapses to `HEAD~1..HEAD` in the worker's clone, and a live R2 suite is already degraded by it).** Measured this session in `/home/scott/Code/HumanOversightSystem/Worker`:

```
git describe --tags --abbrev=0   → fatal: No tags can describe '0b86aa52...'
git rev-parse --is-shallow-repository → true
git tag --list | wc -l           → 19        (tags exist)
git merge-base --is-ancestor v0.6.0 HEAD → NO (none is an ancestor)
```

The clone is **shallow**, so no tag is reachable from HEAD and `git describe --tags` fails outright. E8's derivation then takes its documented fallback (`run_review_chain.sh:127-132`) and resolves the "release range" to **`HEAD~1..HEAD` — one commit** — while logging `since-tag (fallback ...)` and proceeding normally. Applied to a release gate this is the exact failure REQ-A1 forbids, in a costume REQ-A1 does not name: not an *empty* range reporting PASS, but a **degenerate** one. A release panel that reviews one commit and posts PASS over "the release range" is worse than no release panel, because it manufactures evidence.

This is not confined to #1340 — and the mechanism differs per call site. **AMENDED 2026-09-14 (TD-VF-1 accepted, and re-verified by me at `run_validators.sh:344-352`):** the first draft attributed both degradations to the tag/`HEAD~1` fallback. That is right for one call site and wrong for the other:

| Call site | Actual mechanism in this clone | Effective range |
|---|---|---|
| `run_review_chain.sh:121` (tag mode, the default) | shallow → `git describe` fails → documented `HEAD~1` fallback | **one commit** |
| `run_validators.sh:344-347` | tries `git merge-base HEAD origin/main` **first** and succeeds; the tag branch at `:349` is never reached | **empty** (`git diff <merge-base>` on a merged HEAD) — `:373` then skips the `diff_size` validator entirely for want of a file list |

So worker.md's R2 row labelled "`scripts/oversight/run_validators.sh` (diff since last tag)" — **required at every tier** — does not derive from the last tag at all, and in this clone measures nothing. The row's description and its behaviour have diverged, which is a third thing #1630 must record. AF-1's conclusion is unchanged and if anything understated: **a pre-existing live defect in the current release gate, found in passing.** AD-2 closes it for the release panel; ESC-1 puts the clone-level remediation to the human, because it is the older and larger of the two problems.

**AF-2 (CRITICAL — the verdict cannot be a committed file; the obvious design is self-referentially impossible).** REQ-A7 requires the verdict to be valid only for the exact `(range, HEAD sha)` it ran against. ADR-1594's shipped precedent (#555, promote-and-commit) is therefore **unavailable here**, and this must be stated before anyone reaches for it: a verdict attesting `head_sha = X`, committed to the tree, *changes HEAD to Y*. R2 then recomputes `git rev-parse HEAD` = Y ≠ X and fails, permanently, on every release. Any in-tree storage of a HEAD-attesting artifact is a fixed point that does not exist. The artifact must live **out of tree**. AD-4 follows from this, not from convenience.

**AF-3 (HIGH — `token_tracker.py` has zero panel coverage).** `grep -n "panel" scripts/oversight/token_tracker.py` returns nothing. REQ-A12's conditional ("if that path already covers panel invocations") resolves to **no**. Per REQ-A12 this is recorded as a gap, not closed by inventing a tracker (AD-8).

**AF-4 (MEDIUM — `.ai-local/` is gitignored (`.gitignore:3`), so a panel run dir is invisible to any other clone or machine).** Combined with AF-2, this removes both the in-tree and the local-filesystem transports and leaves exactly one: GitHub. AD-4.

### Verification gaps I could not close

- Whether the operator's out-of-band execution will happen in this Worker clone or the Human clone. AD-4's transport is clone-agnostic by construction, so the design does not depend on the answer — but ESC-2 asks it anyway, because the *shallow-clone* remediation (ESC-1) has to be applied wherever the panel actually runs.
- Whether the 19 existing tags become reachable after `--unshallow`, or whether the repo's history was rewritten. If the latter, the base-ref derivation needs an explicit floor and ESC-1 grows. `technical-design` must check this before implementing AD-2 and report, not assume.

---

## 1. Context — what the decision actually is

pm-agent framed the mechanism question as *"new mode on `run_panel.sh`, or a thin wrapper over `panel_logic.py`?"*. After §0 that framing is too coarse, because it treats `run_panel.sh` as one thing. It is two:

- an **engine** (~250 lines, `:387-714`): chunk → fan-out with fail-closed reviewer checks → arbiter → salvage-reconcile → corroboration rank → tier render. This is entirely **mode-invariant** once handed a diff file, a changed-file list, a risk tier, and a roster. It contains every property REQ-A3/A4/A5 demand, already implemented and already wired to `panel_logic.py`.
- five **edges** (~60 lines): where the diff comes from, where context comes from, what the risk floor is, where findings go, and what the verdict says. These are exactly the PR-bound touchpoints of E1, and exactly what release mode changes.

So the real choice is not "fork or reuse". It is **where the seam goes**. Both of pm-agent's options put it in the wrong place: a second file re-implements the engine (D41 violation, explicitly forbidden by the task), and a naive `--release` flag sprinkled through 784 lines forks the engine too.

The seam goes **between the engine and its edges**, and release mode replaces edges only.

One consequence must be stated plainly rather than discovered at release time: because the panel core has never run (E3/E4), **release mode will be the first-ever execution of the engine.** Any latent defect in 250 lines of never-executed shell surfaces during a release cut. That is an argument for AD-9's build order (land the engine inert, demonstrate it out-of-band, arm the gate in a second PR) — not an argument against the design.

---

## 2. Decisions (BINDING on `technical-design`)

### AD-1 — Edge-parameterised mode on `run_panel.sh`, plus a thin `run_release_panel.sh` entry point. The engine is not forked, not copied, and not branched. (BINDING — resolves the mechanism question.)

Two files, with a hard division of labour:

**`scripts/run_panel.sh` (modified)** gains one flag, `--release-range <base_sha>..<head_sha>`, and its five PR-bound edges are lifted into mode-dispatched shell functions. Nothing between `:387` (chunking) and `:714` (tier render) changes:

| Edge | PR mode (unchanged) | Release mode |
|---|---|---|
| diff + file list | `gh pr diff "$PR"` (`:252-253`) | `git diff` / `git diff --name-only` over the range, **minus** the AD-3 exclusions |
| identity + run dir | PR number, `headRefOid`, `pr${PR}-<ts>` (`:218-249`) | range head SHA, `release/<head_sha>-<ts>` |
| risk floor | deterministic floor ∪ author `AI-Risk:` trailer (`:291-297`) | deterministic floor ∪ validator composite over the same range, **floored at MEDIUM** (AD-6) |
| emission | line threads + PR summary comment (`:655-758`) | **no threads**; one issue comment via `post_comment.sh` (AD-5) |
| verdict | `panel-verdict.json` (`:767-769`) | the AD-4 verdict, superset of the same shape |
| **ledger** (`:223`, `:587-650`) | per-PR `pr${PR}-ledger.jsonl`, suppression + `NEW_BLOCKING_COUNT` | **disabled entirely** — AD-10 |

`--release-range` and a PR number are mutually exclusive; supplying both is a usage error, not a precedence rule.

**AMENDED 2026-09-14 (TD-ESC-2, APPROVED).** The first draft asserted "nothing between `:387` and `:714` changes". That is **false**, and the error was mine: I grepped `$PR` and missed the `${PR}` brace form. Two additive carve-outs are authorised inside that span, and no others:

- **(a) `:448`** — `PANEL_ADVISORY_FILE=".claudetmp/panel/advisory-pr${PR}-…"` is a sixth PR-bound edge sitting inside the engine. Resolution: introduce `RUN_LABEL` in the identity edge and derive the filename from it. **BINDING:** in PR mode `RUN_LABEL` must be exactly `pr${PR}`, so `RUN_DIR` and the advisory filename are byte-identical to today; release mode uses `release/<head_sha>-<ts>`, with the advisory filename flattening `/`→`-`.
- **(b) `:481-493`** — two chunk counters inside the existing fan-out loop, incremented in both modes, read only by release mode, no control-flow change. See AD-11 for the increment rule, which is load-bearing.

These are **additive instrumentation and one path parameterisation**. The engine's control flow — chunking, fail-closed reviewer checks, arbiter, salvage-reconcile, ranking, tier render — remains unforked and unbranched, which is what AD-1 exists to protect. Any further edit inside `:387-714` requires a new ruling.

**`scripts/run_release_panel.sh` (new, thin)** is the only thing any caller — operator or R2 — invokes. It owns exactly four things and **no review logic**: range derivation (AD-2), the verdict contract (AD-4), the `--verify` mode (AD-7), and delegation to `run_panel.sh --release-range`.

Grounds, in order of weight:

1. **It is the only option that satisfies the D41 constraint the task imposes.** The engine has exactly one implementation and one invocation site. A second file containing fan-out, arbiter, or ranking logic is forbidden, and this design has no place to put one.
2. **It preserves every REQ-A3/A4/A5 property for free.** Fail-closed on a missing reviewer (`:475-476`), fail-closed on reviewer invocation failure (`:483-486`), arbiter salvage (`:544-554`), Tier-1-before-Tier-2 ordering (`:726-731`): all live in the untouched engine. A forked file would have to re-earn each of them, and #682 and #978 are both scars from getting exactly these wrong once already.
3. **The edges are genuinely small.** Five functions, ~60 lines. The refactor is mechanical: replace an inline `gh` call with a function call whose PR-mode body is the line that was already there.
4. **A separate thin entry point keeps R2's contract clean.** worker.md matches suites **by script path** (AF-1/E10). `run_release_panel.sh` is one stable path with a deterministic exit code; `run_panel.sh` stays the engine and never appears in the R2 table.

**What could still go wrong, stated rather than waved away.** (a) The refactor touches never-executed code, so PR-mode regressions are undetectable by test — mitigated by the fact that PR mode has no working behaviour to regress, and by AD-9 requiring a real out-of-band dry-run before the gate arms. (b) Two modes in one file invite a future edit that assumes one of them; every mode-dispatched function must carry a comment naming both callers. (c) `--release-range` could be passed a range the caller derived badly — closed by AD-2 placing derivation in `run_release_panel.sh` and forbidding a hand-passed range from R2's path.

**Rejected: a second file reusing `panel_logic.py`.** `panel_logic.py` is pure-function logic (floor, SQC, extract-json, aggregate, tier-counts, render-tier, reconcile-arbiter — `:679-707`). It contains **no reviewer fan-out**, because fan-out is CLI subprocess dispatch and lives in bash (`call_model`, `:128-138`). A "thin wrapper over `panel_logic.py`" would therefore have to re-implement the fan-out, the fail-closed checks, the chunking, and the emission — i.e. the entire engine and every property in ground 2. It is thin only in the telling.

### AD-2 — Range derivation is hardened, and a degenerate range is a visible failure, never a PASS. (BINDING — REQ-A1; AF-1.)

`run_release_panel.sh` derives the range with the **same semantics** as `run_review_chain.sh:118-132` (REQ-A1 forbids a third implementation), and then applies three refusals that the existing helper does not have — because that helper feeds validators, where a degraded range is a weak signal, whereas here it is a forged release gate:

1. **Shallow refusal.** If `git rev-parse --is-shallow-repository` is `true`, **exit non-zero** with `range-derivation-failed: shallow clone` and the literal remediation (`git fetch --unshallow --tags`). Do not proceed. Today, in this clone, this is the branch that fires (AF-1).
2. **No `HEAD~1` fallback.** If `git describe --tags --abbrev=0` yields nothing, **exit non-zero** with `range-derivation-failed: no tag reachable from HEAD`. The fallback is correct for validators and catastrophic for a release gate; release mode does not inherit it.
3. **Degenerate/empty refusal.** If the resolved range yields zero files after AD-3 exclusions, emit result `NO-CONTENT` and **exit non-zero**. Never PASS, never silent (REQ-A1).

`technical-design` must implement these as a single function in `release_panel_logic.py` returning a four-state result (`OK | SHALLOW | NO_TAG | NO_CONTENT`), so `--verify` re-derives the base by calling the *same* function the run used. A verifier that derives the base differently from the runner is a gate that can never pass, or worse, one that passes against the wrong base.

### AD-3 — The exclusion list is a committed data file, hashed into the verdict. (BINDING — REQ-A10.)

Path: **`scripts/oversight/release_panel_exclusions.txt`**, following the shipped precedent of `scripts/framework/protected_surfaces.txt` (a committed, line-oriented path list that drives a governance control). One glob per line, `#` comments, applied identically every run.

Initial contents, and the principle behind them — **exclude only what is machine-generated, machine-appended, or archival; never exclude prose that carries governance meaning**:

```
# Generated artifacts — deterministically regenerated, each guarded by its own
# test (docs/GENERATED-ARTIFACTS.md). Reviewing them reviews the generator's
# output, not a decision.
SCRIPTS-INDEX.md
.github/CODEOWNERS
.hos-manifest
scripts/framework/validation-stamps/**

# Machine-appended audit records — append-only, high-volume, no reviewable decision.
audit/log/**
audit/oversight-log.jsonl

# Archival release notes for already-cut releases.
docs/releases/**
```

**Deliberately NOT excluded**, and `technical-design` must not add them: `docs/**` generally, `contract/**`, `.claude/agents/**`, `packs/**`. These are prose, but in this system prose *is* the control surface — an ADR or an agent definition changes what the pipeline does. Excluding "pure docs" wholesale would exempt the governance layer from the governance gate. `audit/log/**` is excluded and `audit/oversight-log.jsonl` is excluded; the `audit/*.md` reports are **not**.

The file's `sha256` goes into the verdict (AD-4) and is recomputed by `--verify` (AD-7), so widening the exclusions after a run invalidates that run's verdict. This is what makes the reduction "data, not judgment" in the enforceable sense rather than the aspirational one.

### AD-4 — The verdict is a JSON object embedded in the issue comment, because it cannot be anything else. (BINDING — REQ-A6, A7, A8; AF-2, AF-4.)

**Transport.** The verdict is emitted as a fenced ` ```json ` block inside the REQ-A2 summary comment on the release-request issue, preceded by the HTML marker `<!-- hos-release-panel-verdict v1 -->`. It is posted by the panel run itself via `bootstrap/post_comment.sh --number <n> --body-file <path> --app worker` (#1155 — never `gh api -f body=@path`).

**Why not the two obvious alternatives**, since both will be proposed again if not closed here:
- *A committed file under `signoffs/`* (the #555 / ADR-1594 pattern): **structurally impossible**, AF-2. Committing a HEAD-attesting artifact changes HEAD. This is not a tradeoff.
- *A file in `.ai-local/panel/`*: gitignored (AF-4), invisible to any other clone or machine. This is precisely ADR-1594's F2 failure — an artifact that never crosses the clone boundary — and repeating it a second time in the same system would be inexcusable.

GitHub is the only transport that is simultaneously out-of-tree, cross-clone, cross-machine, append-only, and already read by the worker (R1.9 check 3 already walks issue comments). One artifact serves both the human (REQ-A2 prose) and the machine (the JSON block) — D41.

**Shape** (`schema_version: 1`; `technical-design` may add fields, may not remove or rename these):

```json
{
  "artifact": "hos-release-panel-verdict",
  "schema_version": 1,
  "result": "PASS | FAIL | NO-CONTENT",
  "range": {
    "base_ref": "v0.6.0",
    "base_sha": "<40hex>",
    "head_sha": "<40hex>",
    "derivation": "since-tag"
  },
  "exclusions": {
    "path": "scripts/oversight/release_panel_exclusions.txt",
    "sha256": "<hex>"
  },
  "coverage": {
    "files_in_range": 0,
    "files_excluded": 0,
    "files_reviewed": 0,
    "files_digest": "<sha256 of the sorted reviewed-path list>",
    "chunks_attempted": 0,
    "chunks_completed": 0
  },
  "risk": {
    "effective_tier": "MEDIUM | HIGH | CRITICAL",
    "deterministic_floor": "…",
    "validator_tier": "…"
  },
  "roster": [{"reviewer": "agy", "lens": "correctness", "status": "ok"}],
  "findings": {"total": 0, "tier1": 0, "tier2": 0, "tier1_undispositioned": 0},
  "arbiter_salvaged": false,
  "run": {
    "run_id": "<uuid>",
    "run_dir": ".ai-local/panel/release/<head_sha>-<ts>",
    "arbiter_sha256": "<hex>",
    "findings_raw_sha256": "<hex>"
  },
  "completed_at": "<UTC ISO-8601>"
}
```

`coverage` is REQ-A8 in machine form and **must also be rendered in the comment prose** — files reviewed/in range, chunks attempted/completed, and the exclusion globs applied — so a human reading the comment sees the coverage claim without parsing JSON. `run.*_sha256` does not let `--verify` check anything (the raw outputs are machine-local), but it makes a later audit on the executing machine decisive rather than speculative.

### AD-5 — Emission: one issue comment, no threads, no LOW skip. (BINDING — REQ-A2.)

Release mode never calls `post_thread` (`:655-659`) — there is no PR diff to anchor to (E2), so the PR path's per-finding thread loop is skipped wholesale rather than allowed to fail 50 times into `UNANCHORED`. Every finding renders into the summary body through the existing `render-tier` calls (`:713-714`), preserving Tier 1 before Tier 2 (`:726-731`). The body gains a `Release candidate SHA: <head_sha>` line and the reviewed range, and retains the IP-placeholder caveat (`:743-745`) unchanged.

### AD-6 — Risk floor and roster: MEDIUM floor, SQC informative only. (BINDING — REQ-A3.)

Effective tier = `max(deterministic floor over range, validator composite over the same range, MEDIUM)`. The MEDIUM floor is applied **before** the `rank < 1` check at `:365-372`, so release mode cannot reach the LOW skip path by any route — not by a low floor, not by an unsampled roll. `technical-design` must implement this as an unconditional clamp at floor-computation time, **not** as a second guard inside the skip branch: a guard inside the branch is one refactor away from being lifted out with it.

SQC (`:335-362`) **may still run and may still log**, because the escaped-defect metric is worth keeping, but in release mode its result is **advisory only** and is forbidden from touching the roster. At MEDIUM the PR path adds an adversary pass *only when sampled* (`:381`); release mode adds `codex:adversary` **unconditionally** per REQ-A3's minimum roster. So the release roster is: `agy:correctness`, `codex:adversary`, `ipcheck:ip` at MEDIUM; `+ codex:security` at HIGH and above. Sampling can only ever be a no-op on this set, which is the literal reading of "must not REDUCE roster".

### AD-7 — `--verify` recomputes everything it can and trusts only what it cannot. (BINDING — REQ-A7, A11; this is the load-bearing decision.)

`run_release_panel.sh --verify --issue <n>` is R2's entry point. It **does not run the panel** and must not be able to: it never invokes `run_panel.sh` and never calls a vendor CLI.

Procedure:

1. Re-derive the range via AD-2's function. Any refusal → **FAIL** with that reason (so a shallow clone fails the *gate*, loudly, rather than silently passing a one-commit review).
2. Read comments via `bootstrap/query_issues.sh --app worker --comments <n>`. Filter to those authored by the worker bot identity. Extract every `hos-release-panel-verdict` block.
3. **Selection rule:** keep only blocks whose `range.head_sha` equals the recomputed `git rev-parse HEAD`; among those, select the **newest by `completed_at`**. Not "the newest block that passes" — that would let a stale PASS shadow a fresh FAIL at the same SHA. Zero candidates → **FAIL: `verdict-missing`**.
4. On that single selected block, **every** check below must hold. Each has a distinct failure reason so R3's excerpt names the cause:

| Check | Verifier action |
|---|---|
| `schema_version == 1` | literal |
| `range.head_sha` | **recompute** `git rev-parse HEAD`, compare |
| `range.base_sha` | **re-derive** via AD-2, compare |
| `exclusions.sha256` | **re-hash** the committed file, compare |
| `coverage.files_digest` | **recompute** `git diff --name-only base..head`, apply exclusions, sort, sha256, compare |
| `coverage.files_reviewed == files_in_range - files_excluded` | REQ-A8 |
| `coverage.chunks_attempted == chunks_completed` | REQ-A8 — a skipped chunk is a FAIL |
| `result == "PASS"` | REQ-A5 |
| `arbiter_salvaged == false` | REQ-A5 / #978 |
| `findings.tier1_undispositioned == 0` | REQ-A5 |

**The principle, and it is the whole point of REQ-A11: anything the verifier can recompute, it MUST recompute rather than read.** Four of the ten checks are recomputations. That is what makes the artifact evidence of an execution rather than an assertion about one — a narrower range or a stale SHA cannot satisfy the gate, because `files_digest` and `head_sha` are derived from the repository at verification time, not copied from the claim. Forging a pass is no longer a matter of writing `"result": "PASS"`; it requires reproducing a digest over the exact post-exclusion file set at the exact candidate SHA.

**Identity is load-bearing, and the text comment stream cannot carry it.** (AMENDED 2026-09-14 — TD-ESC-1, APPROVED.) `query_issues.sh:205-207` renders comments as `--- \(.user.login) @ \(.created_at) ---\n\(.body)\n`, with the body interpolated **verbatim**. Any GitHub user who can comment on the release-request issue can embed a literal `--- hos-worker-hos[bot] @ … ---` line inside their own body, and a text parser splitting on that delimiter attributes the forged verdict block that follows to the worker. Every value in AD-7's recompute set is computable by anyone with a clone — none is a secret — so on the text stream a *passing* verdict is forgeable by an unprivileged third party. **That is a full bypass of the release gate by an outsider, not a residual risk.**

Therefore **BINDING:** step 2 reads through a structured mode — `bootstrap/query_issues.sh --comments-json`, one jq-escaped JSON object per line, in which a comment body cannot emit a record delimiter because jq escapes its newlines. The verifier MUST NOT parse the text `--comments` output. This is a correctness precondition of AD-7, not a convenience: see AD-9 file 12.

**Residual risk, stated not waved away (corrected scope):** the reviewer outputs themselves (`arbiter.json`, `findings.raw.json`) are machine-local and gitignored, so `--verify` cannot confirm that the *reviews* happened — only that an artifact consistent with the current repository state was posted **under the worker App identity**. An actor holding the worker bot token could hand-craft a matching block. That is the irreducible residue of AF-2 + AF-4 (no in-tree, no cross-machine filesystem transport exists), and it is bounded by **token custody** — a real control — and by the effort of reproducing the digests. The first draft of this paragraph claimed the bound was "identity (`--app worker`)" while AD-7 step 2 read a stream in which identity was forgeable; that claim was **false as written** and is corrected here. Record the limit in the DECISIONS entry in these corrected terms.

### AD-8 — Cost visibility is a recorded gap, not an invention. (BINDING — REQ-A12; AF-3.)

`token_tracker.py` has no panel coverage at all (AF-3), so REQ-A12's condition is not met. `technical-design` must **not** build a tracker. The gap is recorded in the DECISIONS entry and in a follow-up issue (§5 FU-2). The verdict's `roster[]` gives a coarse proxy (which CLIs ran, over how many chunks) at zero cost; include it, and do not describe it as cost tracking.

### AD-10 — Release mode disables the SPEC-78 ledger outright. (BINDING — TD-ESC-3, APPROVED; REQ-A5.)

With `$PR` empty, `PANEL_LEDGER` (`:223`) collapses to a single shared `.ai-local/panel/pr-ledger.jsonl` across every release run. That is not merely untidy: `:777` gates the exit code on `NEW_BLOCKING_COUNT`, **not** `TIER1_COUNT`, so a tier-1 finding recorded once would be suppressed on every subsequent release forever — a permanent, silent softening of AD-7 check 10 and REQ-A5.

Release mode therefore **skips both Python blocks** (`:588-618` and `:629-650`) entirely. The ledger's purpose (SPEC-78) is convergence across iterations of *one PR* — don't re-surface a finding the author already triaged — and release mode has no iteration semantics, no author responding, and, per AD-5, no threads to suppress. There is nothing for it to do.

**Rejected: a release-scoped ledger keyed on head SHA.** It would be empty on the first run at any SHA (so it buys nothing REQ-A7's verdict-level idempotency does not already provide), and on the second run at the same SHA it becomes a **laundering path** — re-run until the tier-1s are ledgered and the verdict comes back clean. Strictly worse than none.

**BINDING details, because disabling the load is not sufficient on its own:**
- `NEW_BLOCKING_COUNT` retains its initialisation at `:587` (`="${TIER1_COUNT}"`), so `:777` still escalates on any tier-1; `SUPPRESSED_COUNT` stays `0`.
- The verdict's `findings.tier1_undispositioned` maps to **`TIER1_COUNT`, never `NEW_BLOCKING_COUNT`**. Wiring it to the latter would look identical today and would silently soften check 10 the moment anyone reintroduces a ledger.

### AD-11 — Chunk counters must distinguish a swallowed failure from a success, or check 7 is decorative. (BINDING — TD-ESC-2(b); REQ-A8.)

Approved, with the increment rule specified — because the obvious implementation makes the check meaningless. Every non-`ipcheck` reviewer already `die`s on a failed chunk (`:483-486`, #682), so a run that completes *cannot* have `attempted != completed` for those reviewers; naively incrementing both counters in lockstep yields a check that is trivially true in every verdict ever written.

The one reviewer that degrades **silently** is `ipcheck`: `:484-487` substitutes `{"findings":[]}` and continues. **BINDING:** `chunks_completed` increments only on a genuine reviewer response; the `ipcheck` fallback path counts as **attempted, not completed**. That makes REQ-A8's "a chunk that failed to review is a FAIL" real for the single reviewer that currently swallows failures, and leaves check 7 as defence-in-depth if a future edit ever softens the `die`.

Both counters count **reviewer-chunk pairs** (roster size × chunk count), not files. Say so in the field documentation so `chunks_*` is never misread against `files_reviewed`.

### AD-9 — Scope: two PRs, and the gate arms second. (BINDING.)

**PR 1 — the engine and the contract, deliberately inert (~11 files):**

| # | File | Note |
|---|---|---|
| 1 | `scripts/oversight/release_panel_logic.py` | **new** — range derivation (AD-2), exclusion application, verdict compose, verdict verify. The verdict contract lives here and **nowhere else**. **AMENDED 2026-09-14 (TD-VF-6):** "no subprocess CLI calls" meant **no vendor-CLI calls** (`agy`/`codex`/`claude`) — `git` is obviously required by AD-2 and is permitted. TD's reading is correct and the stricter one was never intended. **BINDING:** the `git` calls are confined to one injectable seam so every AD-2 refusal and every AD-7 recomputation is unit-testable without a real repository. |
| 2 | `scripts/run_release_panel.sh` | **new** — thin entry point; execute + `--verify`. No review logic. |
| 3 | `scripts/run_panel.sh` | **modified** — five edges lifted into mode-dispatched functions; `--release-range`; engine untouched. |
| 4 | `scripts/oversight/release_panel_exclusions.txt` | **new** — AD-3. |
| 5–8 | tests | `tests/oversight/test_release_panel_logic.py` (AC 1,3,6,7,8 + all four AD-2 refusals + all ten AD-7 checks + the AD-7 §3 shadowing case), plus a shell-level smoke for `--verify` against a fixture comment. |
| 9 | `DECISIONS.md` | REQ-D — see §4. |
| 10 | `SCRIPTS-INDEX.md` | regenerated via `scripts/framework/regen_all.sh`. |
| 11 | `METHODOLOGY.md` | one line placing the release panel in the pipeline diagram. |
| 12 | `bootstrap/query_issues.sh` | **modified, AMENDED 2026-09-14 (TD-ESC-1, APPROVED)** — additive `--comments-json` mode. Not a scope concession: without it AD-7's identity bound is forgeable by any commenter and the gate is bypassable by an outsider. Additive only — the existing `--comments` text mode and all its current callers are untouched. Correctly placed on the canonical GitHub reader rather than in a second one (D41). |

Nothing in PR 1 touches `worker.md`. The suite is therefore **not yet required by R2**, nothing gates on it, and a defect in never-executed engine code cannot block a release.

**PR 2 — arming (~3 files):** `.claude/agents/worker.md` (REQ-C1/C2/C3: the R2 row, required at MINOR/MAJOR only, and the PATCH-promotion rule's "all five suites" → "all six"), `docs/OVERSIGHT-RUNBOOK.md` (the operator's out-of-band procedure), `DECISIONS.md` (append the arming). `worker.md` is a protected surface: per `CLAUDE.md` it is hand-authored by the orchestrating session, never by `coder`, and carries a human-approval gate at merge.

**The gate between them is not administrative.** Because the engine has never executed (E3/E4), PR 2 must not open until the release panel has been run **once, out-of-band, for real**, and has produced a verdict that `--verify` accepts. Arming R2 with an unexecuted suite would make every MINOR/MAJOR release cut fail on `verdict-missing` from the moment it merges — ADR-1594 AF-3's mistake, repeated. This is the same "a partial landing is never a live half-gate" rule that ADR's build order used.

**Out of scope, explicitly:** REQ-B7/B8 (`overseer.md`'s release-gate section — blocked on #1622/#1623/#1624 per REQ-B8's binding ordering; **PR 1 must not touch that section at all**); REQ-A13 (#1625); a token tracker (AD-8); the shallow-clone remediation itself (ESC-1); consumer-side impact (#1621).

---

## 3. Answers to the questions as asked

- **Mechanism?** Edge-parameterised mode on `run_panel.sh` (`--release-range`), driven by a thin `run_release_panel.sh` that owns derivation, the verdict contract, and `--verify`. The engine is neither forked nor re-implemented. pm-agent's option (b) is rejected because `panel_logic.py` contains no fan-out, so a "thin" wrapper over it is the whole engine again (AD-1).
- **Verdict contract?** A `schema_version: 1` JSON object in a marked fenced block inside the issue comment — the only available transport, since in-tree storage is self-referentially impossible (AF-2) and `.ai-local/` is gitignored (AF-4). R2 verifies it by **recomputing** head SHA, base SHA, exclusion-file hash, and post-exclusion file digest, and comparing (AD-4, AD-7).
- **New script or extend an existing one?** New: `run_release_panel.sh` + `release_panel_logic.py`. R2 matches suites by script path (E10/AF-1), so the suite needs one stable path of its own; folding `--verify` into an existing suite would make R1.9's anchor walk ambiguous.
- **One PR or several?** Two (AD-9), split at the arming boundary, with a demonstrated out-of-band run required between them.

---

## 4. REQ-D — DECISIONS.md entry (draft; `technical-design` may tighten prose, not change substance)

Scoped to what PR 1 actually does. Must contain: **problem** — the release gate checked for step artifacts this repo has never produced, while the one genuinely independent review mechanism (the panel) had never run at all (E3/E4); **decision** — retire-and-rehome, of which this delivers the REQ-A execution capability, with the REQ-B guarantees split to #1622/#1623/#1624/#1625 and the `overseer.md` removal (REQ-B7/B8) deferred until those land; **rejected alternative** — per-PR panel backfill (option (b)), rejected because the panel has never run per-PR and a backfill would land findings on merged, closed PRs that nothing gates; **what it does** — one paragraph per REQ-D5: reviews `<last-tag>..HEAD` minus a committed exclusion list, full cross-vendor roster floored at MEDIUM, fail-closed on any missing reviewer, posts one summary comment plus a machine-readable verdict to the release-request issue, and is verified at R2 by recomputation rather than trusted; **scope and residual gaps** — `overseer.md`'s section is untouched; #1621 (consumer impact) open; AD-8's token-tracking gap; AD-7's residual forgeability; and **AF-1**, that the worker's clone is shallow so the existing `run_validators.sh` "diff since last tag" R2 suite is *already* scoring one commit per release.

---

## 5. Follow-up issues to file (named, not filed by me)

- **FU-1 — arm R2 (REQ-C).** PR 2 of AD-9. Blocked on a demonstrated out-of-band run.
- **FU-2 — `token_tracker.py` does not cover panel invocations (AF-3).** Release-panel external-CLI spend is untracked; REQ-A12's condition is unmet.
- **FU-3 — shallow clone breaks every "since last tag" derivation (AF-1). `priority:high`, and *not* scoped to #1340.** It already degrades `run_validators.sh:349` under a currently-required R2 row, and `run_review_chain.sh:121`. This is a live defect in the existing release gate, independent of whether #1340 ever lands.
- **FU-4 — REQ-B7/B8** is already tracked and blocked on #1622–#1625; no new issue needed.
- **FU-5 — the comment text stream is author-forgeable; migrate every author-filtering reader to `--comments-json` (AMENDED 2026-09-14, TD-ESC-1).** `priority:high`, wider than #1340. `query_issues.sh:206` interpolates comment bodies verbatim into a `--- <login> @ <ts> ---` delimited stream, so any commenter can forge the delimiter and impersonate any login to a text parser. #1340's verdict is the **first PASS-bearing consumer** of this stream and therefore must not ship on the text parser — that is closed inside PR 1 by AD-7. The general hardening is not. Assessed exposure of the existing readers, so the follow-up is scoped rather than alarmed: worker.md R1.9 check 3's anchor walk is largely self-protecting (an anchor must record a **FAIL**, and a forged FAIL halts the pipeline rather than passing anything — the worst case is a ≤6-hour suppression of a suite that would have failed anyway), and R4's authorization check keys on self-assignment and timestamps, not on comment text. The issue is therefore hardening against the *next* PASS-bearing reader, not an active bypass in the current ones.

---

## 6. Escalations

### Bound here, not escalated — with reasons

- **Edge-parameterisation over a second file** (AD-1): bound technically; the D41 constraint and the fail-closed properties in the engine settle it.
- **Comment-as-transport** (AD-4): bound, because AF-2 makes the alternative impossible rather than merely worse.
- **Recompute-don't-trust** (AD-7): bound; it is the only reading of REQ-A11 that distinguishes evidence from a claim.
- **No `HEAD~1` fallback in release mode** (AD-2): bound, even though it means the release panel **cannot run in this clone today**. Failing loudly is the correct behaviour; ESC-1 is how it gets fixed.

### ESC-1 — The worker's clone is shallow, which breaks a currently-required R2 suite. (Operational obligation — human.) — AF-1

`git rev-parse --is-shallow-repository` is `true` and no tag is an ancestor of HEAD, so **today** `run_validators.sh` (required at every tier in R2) scores `HEAD~1..HEAD` and reports PASS for a whole release. AD-2 makes the release panel refuse rather than inherit this, but the underlying clone problem is older and wider than #1340 and I will not paper over it. Options: (a) `git fetch --unshallow --tags` in the worker clone and add a shallow assertion to `smoke_test.sh` — recommended; (b) leave it and accept that "diff since last tag" means "last commit" in this clone; (c) change the derivation everywhere to a pinned base ref. The human owns this because it changes the clone's operational setup and because (b) is a decision to keep a known-degraded gate. **Also required: confirm whether the 19 existing tags become ancestors after `--unshallow`, or whether history was rewritten** — if the latter, (a) is insufficient and the remediation grows (§0, verification gaps).

### ESC-2 — Out-of-band execution: who runs it, where, and at what cost. (Product/operational — human.) — REQ-A11, ESC-2's own ruling

The design is settled (R2 verifies, does not execute), but three operational facts are not mine to set: **who** runs the release panel (the human, presumably, since the vendor CLIs hold interactive OAuth); **in which clone** (this matters only because ESC-1's remediation must be applied wherever it runs); and **the cost**, which is a full cross-vendor roster over an entire release range, chunked — materially larger than any per-PR panel, and untracked (AD-8). If the answer is "too expensive to run every release", that is a product decision about the gate's frequency and must be made deliberately now rather than discovered as a skipped suite later. **Per the product-boundary checkpoint this is routed before the R2 arming (PR 2) binds** — it adds a new operational obligation to the release process. AD-9's two-PR split means PR 1 can proceed while this clears.

---

## 7. Startup-gap analysis and affected sign-offs

**Should any of this have been settled in the initial architecture review, before design and code were built against it?**

- **AF-1 (shallow clone) — yes, and it predates #1340.** The "diff since last tag" R2 row was designed on a premise — that a tag is reachable from HEAD — that does not hold in the environment the worker actually runs in. **This is a `startup-artifact-gap`**, and FU-3 must be filed as one. **Affected sign-offs:** #1340 has no design or code yet, so nothing here is orphaned. The prior sign-off on whichever issue introduced the `run_validators.sh` R2 row is **not invalidated** — the code does what it was approved to do — but its *coverage claim* was never true in a shallow clone, so FU-3 must re-check that row's behaviour rather than assume it. No approved code needs re-review; one approved **claim** does.
- **AF-2 (the committed-verdict impossibility) — no.** pm-agent correctly left the mechanism to architecture, and REQ-A7 stated the constraint that makes the impossibility derivable. The process worked.
- **AF-3 (token tracker) — no.** REQ-A12 anticipated exactly this and specified the conditional. Recording the gap is the specified outcome.

No `technical-design` or `coder` output exists for #1340, so **no sign-off is orphaned by this ADR** and none requires re-review. The single re-check obligation is FU-3's, above.

---

## Human Review Required

**RISK: MEDIUM-HIGH.** Not because the change is large — PR 1 is ~11 files of mostly-new, mostly-Python logic — but because it builds a **release gate**, and a release gate that passes wrongly is worse than none. The two ways this could have gone wrong silently are closed positively above rather than cautioned about: (1) the mandated range derivation resolves to a **one-commit** range in this clone and would have posted PASS over "the release range" (AF-1 → AD-2's three refusals, which make the panel *fail* in this clone until ESC-1 is resolved — deliberately); (2) the natural verdict design, a committed artifact following this repo's own #555/ADR-1594 precedent, is **self-referentially impossible** and would have produced a gate that can never pass (AF-2 → AD-4). A third — a verifier that reads the claim instead of recomputing it — is closed by AD-7 making four of ten checks recomputations.

**CONFIDENCE: HIGH** on §0; every finding was re-derived from the working tree this session, including the three that extend pm-agent (**AF-1**: shallow clone, measured, and it already degrades a live R2 row; **AF-2**: the in-tree verdict is a fixed point that does not exist; **AF-3**: zero panel coverage in `token_tracker.py`). **HIGH** on AD-1 through AD-7, which follow from those findings and from code read line-by-line this session. **MEDIUM** on AD-3's specific exclusion contents — that is a judgment about what is genuinely generated in this repo, cross-checked against `docs/GENERATED-ARTIFACTS.md` but worth a reviewer's eye. **LOWER** on the out-of-band cost estimate in ESC-2, which I cannot measure because the panel has never run.

**BLAST RADIUS:** the release gate — i.e. whether a MINOR/MAJOR release may be cut — once PR 2 arms it; `run_panel.sh`, which is shipped to every consumer install and whose PR mode is refactored here; a new required R2 suite in `worker.md` (protected surface, human-gated); and, via FU-3/ESC-1, the coverage claim of an **already-required** R2 suite. PR 1 alone has a deliberately null blast radius: nothing invokes it.

**Change classification: STRUCTURAL.** A new gate, a new machine-readable artifact class with a verification contract, a refactor of a shipped script's control flow, and a protected-surface edit in PR 2. Per the product-boundary checkpoint, **ESC-1 (operational obligation) and ESC-2 (execution ownership and cost) must be cleared by the human before PR 2 binds**; PR 1 may proceed on `technical-design`'s completion.
