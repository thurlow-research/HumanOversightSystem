# Label registry

Single authoritative answer to "what does this label do, who writes it, and
where does its name live in code." Written per the #1349 ruling
(`DECISIONS.md`, 2026-09-06) as the "one authoritative place" for label
semantics. Doc-only — this registry does not itself change any control flow;
it records what the code (as of this writing) already does.

**Names are fixed literals, not configurable.** They are hardcoded across
`scripts/automation/lib/probe.py`, `bin/hos-cron`,
`scripts/automation/lib/next_candidates.jq`, `.github/workflows/label-swap.yml`,
and `scripts/automation/lib/merge_authority.py`. There is no runtime
label-name configuration anywhere in this repo — `scripts/framework/machine-accounts.env`
holds account identity and threshold config (`OVERSEER_CEILING`,
`HUMAN_REVIEWER`, `BOT_ACCOUNTS`) only, no label names. A consumer using a
different naming convention (e.g. `needs_ai` with an underscore) is
unsupported — do not attempt to detect or reconcile a local variant at
runtime.

**Pending rename.** Per the #1349 ruling (`DECISIONS.md`, 2026-09-06),
`needs-ai` is planned to be renamed to `needs-worker`, with a new
`needs-overseer` label introduced alongside it. That migration has **not**
happened yet — every row below reflects the current, pre-migration code as of
this writing. Do not treat `needs-worker`/`needs-overseer` as live; they are
not written or read anywhere yet.

| Label | Writers | Control-flow effect | Notes |
|---|---|---|---|
| `needs-ai` | `.github/workflows/label-swap.yml` (`/approve`, `/handoff`); `merge_authority.py` (`labels_to_add` on the oversight-verdict-not-PROCEED path, `:599`; `record_pr_bounce()` default label, `:1068`); `self_review_source.py:229` (`file_finding_as_issue()`, alongside `hos-coordination`, at issue-creation time when filing a self-review finding) | **On issues:** work-selection filter — `probe.py:320`, `bin/hos-cron:1123` query by `labels=needs-ai`; `next_candidates.jq` excludes any issue also carrying `needs-human`. **On PRs:** `bin/hos-cron:1085` reads `draft == true` AND `needs-ai` present to detect an overseer bounce and route the worker to `needs-fix-bounce` (`#1350`, shipped `c4f5e905`). Otherwise not consulted by `merge_authority.py`'s own PR-label gate (`_HUMAN_GATE_LABELS`, below), which does not include it. | The same label name is used for two different directions on a PR (worker→overseer handoff vs. overseer→worker bounce), disambiguated by draft state plus, since `#1350`, by the label itself in the bounce-detection check. See `DECISIONS.md` 2026-09-06 entry (#1349) for the planned `needs-worker` rename and why an earlier draft ruling to *not* rename was reversed. |
| `needs-human` | `.github/workflows/label-swap.yml` (`/handoff` only — `/decline` *removes* this label, it does not write it); `merge_authority.py` (multiple `HUMAN_REQUIRED` paths, e.g. NG3b release guard `:586`, oversight-verdict ESCALATE `:599`, `route_embargo()` `:770`); `overseer.md` `HUMAN_REQUIRED` escalation path; worker NG3b release-authorization protocol (R4 step 0b, on `release-request` issues only); `bootstrap/hos_install.sh` (best-effort, install time) | **Hard merge block** on PRs — `merge_authority.py:468,526` (`_HUMAN_GATE_LABELS`), independent of risk tier (#756). **Issue triage short-circuit** — `triage.py:198-206`, authoritative, overrides other classification. **Work-selection exclusion** — `next_candidates.jq` excludes labelled issues. **Broken-state sweep target** — `bin/hos-cron` queries by this label at several points (e.g. `:954`, `:1659`, `:1947`, `:2051`, `:2075`). **On `release-request` issues only: NG3b authorization signal** — the worker applies it itself (R4 step 0b) as part of posting the release authorization request, and the human's *removal* of it is one of three required signals verified live from the GitHub Events API (`.claude/agents/worker.md` "Release authorization protocol"). | This is the one label in this table that is genuinely load-bearing in more than one, unrelated way. Any future change to this label's meaning must independently satisfy the merge-block, triage, and NG3b uses. `/approve` and `/decline` (`label-swap.yml`) both *remove* `needs-human` (to `needs-ai` or `wontfix` respectively) — neither writes it. |
| `hos-halt` | Not provisioned as a label anywhere in this repo — `docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md` R8.4 states the kill switch is a **file**, never a label. A human can still hand-apply it. | **Hard merge block** on PRs if present — `merge_authority.py:468` includes it in `_HUMAN_GATE_LABELS` regardless of provisioning. **Whole-cycle halt** — independently, `bin/hos-cron:918` queries open **issues** carrying this label before either `--role worker` or `--role overseer` runs; if any are open, or if the check itself fails, the entire cron cycle is skipped fail-closed (`#793`/`#912`). This is a separate, larger control-flow effect than the PR merge-block above — it gates both roles system-wide via any open issue, not just a specific PR. | A documented contradiction: the spec forbids creating this label, but the code still honours it as a block (both as a PR-merge gate and as an issue-based cron kill switch) if a human hand-applies it. This is fail-closed in the only direction that matters (a stray label can block/halt, never authorize) and is not resolved by this registry — tracked as a follow-up. |
| `hos-claimed` | Removal only is implemented: `scripts/automation/lib/claim.py:284-286` (terminal claim-release) and `.claude/agents/worker.md:379` (step 10, via `bootstrap/edit_issue.sh --remove-label`). No code path that *adds* this label was found by repo-wide search — how/where it gets applied in the first place is not currently traceable to source. | None found beyond the removal above; not consulted by any routing/gate logic in `merge_authority.py`, `bin/hos-cron`, or `triage.py`. | Flagged, not fixed, by this registry: the add-path gap is a real documentation/implementation gap, not just an unverified claim — worth its own follow-up. |
| `hos-embargo` | `scripts/automation/lib/merge_authority.py:770` (`_handle_security_report`/`route_embargo()`, applies `["hos-embargo", "needs-human"]` together). `triage.py` only sets an internal boolean `embargo` flag — it does not call the GitHub API itself; `merge_authority.py` is the actual writer. | Not consulted by any routing/gate logic found in this pass — appears to be informational/human-facing only, layered on top of the `needs-human` block it's always applied alongside. | |
| `hos-coordination` | `scripts/automation/lib/self_review_source.py:229` (`file_finding_as_issue()` applies it, alongside `needs-ai`, at issue-creation time when filing a self-review finding); may also be applied by a human or coordinating actor out-of-band. Consumed by `scripts/automation/lib/probe.py` (coordination strategy). | `probe.py`'s coordination strategy requires actor verification — an allowlisted actor must be the one who applied it, checked live via GitHub events, same actor-verification pattern as NG3b's self-assignment check. | `scripts/framework/check_agents_static.sh:158`'s `KNOWN_LABELS` allowlist spells this `needs-coordination` (wrong prefix) — a **pre-existing mismatch** against the real usage sites (`probe.py`, `self_review_source.py`), which use `hos-coordination`. Out of scope for this PR; tracked as a follow-up. |
| `hos-budget-gated` | Not written by `budget.py` itself — that module only computes the gate *decision*. The label is applied manually by the worker agent following its own instructions (`.claude/agents/worker.md`, via `bootstrap/edit_issue.sh --add-label hos-budget-gated`). | None found in `merge_authority.py`/`bin/hos-cron` routing — informational marker of the gate decision, not itself consulted downstream in this pass. | |
| `hos-in-progress`, `hos-autowork-authorized`, `suppression-expired` | **Not found in any executable code path** (`.py`/`.sh`) by repo-wide search as of this writing — these names appear only in `docs/specs/UNATTENDED-WORKER-TECH-DESIGN.md` / `UNATTENDED-WORKER-PROTOCOL.md` (planned) and in `check_agents_static.sh:158`'s allowlist. | None — unimplemented. | Do not treat these as live signals; they are planned/spec-stage only. Confirm against the tech-design doc's own status markers before relying on them. |
| `release-request`, `release-authorized` | Hand-created labels, no provisioning script (`docs/MACHINE-ACCOUNTS-SETUP.md` Step 8) | `release-request` triggers the NG3b release-authorization protocol (`.claude/agents/worker.md`). `release-authorized`, together with `needs-human`'s removal and a qualifying self-assignment (all by the same CODEOWNER), is one of the three required NG3b authorization signals (R5). | See NG3b (`.claude/agents/worker.md` "Release authorization protocol") for the full signal-verification sequence. Neither label is auto-applied by any automation — both require deliberate human action. |
| `priority:critical` / `priority:high` / `priority:medium` / `priority:low` | Applied during triage (Step 0 of the worker loop) or at issue-filing time | Ordering signal only — `bin/hos-cron`'s "Next work candidates" ordering sorts by this label (critical > high > medium > low; no label ⇒ low), then lowest issue number within a band. Does not gate selection eligibility (that's `needs-ai` + milestone + not-`needs-human`). | |

## Known gaps (not fixed by this registry)

- **No idempotent provisioning path.** `release-request`/`release-authorized`
  are two hand-run `gh label create` commands documented in a setup guide;
  the `hos-*` set is a list in a tech-design doc; `hos_install.sh` applies
  `needs-human` best-effort with a printed tip on failure. There is no single
  script that provisions every label in this table into a fresh consumer
  repo. Tracked as a follow-up from #1349.
- **No conformance test.** Nothing currently asserts that the label literals
  hardcoded in `probe.py`, `bin/hos-cron`, `next_candidates.jq`,
  `label-swap.yml`, and `merge_authority.py` match this table, or that a
  label documented here as "informational" truly has no reader. Tracked as a
  follow-up from #1349.
- **The planned `needs-worker`/`needs-overseer` rename** (see "Pending
  rename" above) is not implemented. Migration scope — ~65 files touching
  `needs-ai` in live code, agent definitions, prompts, and tests; live
  GitHub issue relabeling; and a breaking-change story for at least one known
  consumer project running its own worker/overseer cron against the current
  convention — is tracked in a dedicated follow-up issue, not this one.
- **`scripts/framework/check_agents_static.sh`'s `KNOWN_LABELS` list** is a
  separate, narrower enumeration used only to validate agent-file escalation
  targets — it is not this registry and should not be treated as a second
  source of truth for label behaviour.
