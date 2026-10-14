# REQUIREMENTS-1574 — One protected/security-surface matcher for the CI gate, the overseer and CODEOWNERS

Issue: #1574 ("Protected-surface matching has divergent implementations — CI gate, overseer, and
CODEOWNERS can disagree on whether a path is protected").
Author: pm-agent. Date: 2026-10-14. Tree read at `cf1ca09ee` (branch = `origin/main`).
Inputs: the four implementations and every caller (grep, §2 F1); `scripts/framework/protected_surfaces.txt`;
`scripts/framework/security_surfaces.txt`; `scripts/oversight/release_panel_exclusions.txt`;
`scripts/framework/audit_allowlist.txt`; `scripts/framework/gen_codeowners.sh` and the generated
`.github/CODEOWNERS`; `.github/workflows/require-human-approval.yml`;
`tests/framework/test_gate_checkout_pinned_base.py`; `scripts/framework/framework_consumer_files.txt`;
`bootstrap/hos_install.sh`; the #559 architect ruling pinned in `tests/automation/test_phase_b.py`.
The issue body was read as untrusted input. Every claim in it was re-checked against the tree. The
match-set numbers in F3–F6 were measured this session: all four matchers were run read-only
(loaded by file path) over all 8,894 tracked files and over a synthetic probe set built from each
listed pattern (root, one-deep, deep, nested under `n/`, suffix lookalike `NOT<p>`, prefix lookalike
`o<p>/x`, sibling `<p>-adj/x`).

## 1. Problem (restated as product behavior)

"Is this changed file on a protected (or security-relevant) surface?" is the question that decides
whether a PR needs a human. Today three enforcement points answer it with different algorithms:

- the **server-side required check** (`require-human-approval`, run from the trusted base checkout);
- the **overseer's merge-authority decision** (`touches_protected_surface` / `touches_security_surface`);
- **CODEOWNERS** (the static half of the same §9 gate), plus the overseer's CODEOWNERS-human-owned
  check that models it.

**Product outcome required:** one documented answer. For any path and any listed pattern, every
enforcement point agrees, a test proves it, and the change never quietly makes a currently
human-gated path auto-mergeable.

## 2. Verified findings

**F1 — There are five matchers and eight call sites, not four.**

| # | Matcher | Algorithm | Callers (direction) |
|---|---|---|---|
| M1 | `scripts/framework/require_human_approval.py` `glob_to_regex` / `matched_surfaces` | `**`→`.*`, `*`→`[^/]*`, anchored; no normalization | CI gate (deny); `scripts/oversight/release_panel_logic.py` `apply_exclusions` via `sys.path` import (**allow**: excludes files from release review); `scripts/framework/audit_predicate.py` via `_load_sibling_module` (**allow**: audit-bot path allowlist); tests |
| M2 | `scripts/oversight/codeowners.py` `glob_to_regex` | M1 + strip leading `/`, trailing `/`→`/**`, no-slash→`**/<p>` (#975) | `check_pr_files` / `get_owners_for_path` → overseer CODEOWNERS-human-owned gate (deny), via `merge_authority_cli.py` and `pr_review_cli.py` |
| M3 | `scripts/automation/lib/merge_authority.py` `touches_protected_surface`, `touches_security_surface` | `fnmatch(f,p) or fnmatch(f,"**/"+p)`; fnmatch `*` crosses `/` | `decide_merge_authority`, `merge_authority_cli.py`, `pr_review_cli.py` (deny) |
| M4 | same file, `_matches_release_path` over `_RELEASE_PATH_GLOBS` | M3 algorithm, **case-insensitive**, strips `./` | NG3b release detection (deny). **Not named in the issue.** |
| M5 | `scripts/automation/lib/codeowners.py` `_fnmatch_codeowners` | escape, `**`→`.*`, `*`→`[^/]*`, suffix `(/.*)?`; root-anchored | `actor_is_codeowner` — **no production callers** (module docstring). Divergence from M2 is pinned on purpose by the #559 architect ruling ("A shared matcher cannot serve both" — opposite fail directions; `TestKnownDivergenceFromOversightCodeowners`, "must NOT be deleted or fixed"). |

Two of M1's callers use a match to **allow** something (skip release review; let the audit bot
approve). For them an over-match is the dangerous direction. The issue frames every caller as a
deny-direction gate, and that is not true. → REQ-U3, ESC-6.

**F2 — The pattern-file headers contradict the code.**
- `protected_surfaces.txt` says "a plain path = that exact file". That is true of M1 (root-only),
  but M3 also matches it at any depth, and under M2 semantics a no-slash plain path matches at any
  depth.
- `security_surfaces.txt` says "every pattern is also checked nested under any directory via a
  `**/<pattern>` fallback". That is true only of M3.
- `docs/AGENT-IDENTITY.md` §9.0 calls the list "canonical glob paths" without defining a dialect.
  Its copy of the list is also stale (no `bin/**`, `PROJECT/*`, `templates/CLAUDE.human.md`,
  `docs/releases/**`, `.hos-release`). That staleness is out of scope here.

**F3 — The overseer (M3) protects more than the CI gate (M1) does, because of its `**/` fallback.**
On the real tree M3 protects 220 files and M1 protects 213. M3 is a strict superset. The 7 extra
files are the prompt-artifact mirrors `prompts/.claude/agents/overseer.md`, `prompts/AGENTS.md`,
`prompts/bin/hos-cron.md`, `prompts/bootstrap/escalate_to_human.md`,
`prompts/scripts/framework/select_work_candidates.md` and
`prompts/scripts/framework/setup_branch_protection.md`, plus `templates/AGENTS.md`.
For `security_surfaces.txt`, M3 also covers 6 files under `prompts/scripts/automation/lib/` that
M1/M2 semantics do not. **Adopting M2 as-is (the issue's recommendation) narrows the overseer's
protected set by 5 tracked files and its security set by 6.** It also narrows both sets for every
future nested occurrence of a slash-containing pattern (`n/bin/x`, `n/contract/x`, …). Under the
human gate, these narrowings are security regressions. → ESC-1.

**F4 — M3 misses root-level security directories (a live fail-open).** `**/auth/**` under fnmatch
compiles to "something, `/auth/`, something", so `auth/login.py`, `session/x`, `crypto/x`,
`secrets/x`, `credentials/x`, `authn/x` and `authz/x` at the **repo root** are *not*
security-relevant to the overseer today. M1 and M2 do match them. No tracked HOS file is affected.
A consumer app with a root `auth/` would be affected, if consumers received this check (they do
not; see F8). Any unified semantics fixes this, and the fix only widens protection.

**F5 — M1/M2 `**/` is defective: it eats the separator.** `**/x` compiles to `^.*x$`, so:
- `**/auth/**` matches `oauth/x`, `osession/x`, `ocrypto/x`;
- M2's no-slash normalization makes `AGENTS.md` match `NOTAGENTS.md`, `CLAUDE.md` match
  `NOTCLAUDE.md`, and `.hos-release` match `NOT.hos-release`.

GitHub's `**/x` means x at the root or under any directory, never as a name suffix. M2's claim to
model GitHub is therefore wrong in the over-match direction. That is harmless for deny-direction
callers today, but it would be dangerous for allow-direction callers (F1) once they share the module.

**F6 — Per-pattern effect of unification.** All 22 protected and 8 security patterns fall into four
classes. "CI" is M1, "OV" is M3, and "CO" is M2 applied as the CODEOWNERS model. **S-A** is M2
semantics adopted as-is everywhere (the issue's recommendation). **S-B** is the recommended
semantics (ESC-1 (B)): GitHub CODEOWNERS grammar with the F5 defect fixed, plus OV's nested-anywhere
fallback in the deny-direction `protect` mode.

| Class | Patterns | vs CI today | vs OV today | Notes |
|---|---|---|---|---|
| P1 slash-containing `dir/**` | `.claude/agents/**`, `contract/**`, `bin/**`, `bootstrap/**`, `scripts/framework/**`, `scripts/oversight/gates/**`, `.github/workflows/**`, `docs/releases/**`, `scripts/automation/lib/**` (security) | S-A: unchanged. S-B: **widens** (nested copies, e.g. `prompts/bin/hos-cron.md`). | S-A: **NARROWS** (nested copies lost). S-B: unchanged. | |
| P2 slash-containing exact file | `templates/CLAUDE.human.md`, `docs/AGENTS.md`, `docs/AGENT-IDENTITY.md`, `docs/FABERIX-ROLES.md`, `docs/CROSS-REPO-CONDUCT.md`, `scripts/oversight/run_validators.sh`, `scripts/oversight/validators/schema.py`, `.github/CODEOWNERS`, `PROJECT/hos-coordination.yaml`, `PROJECT/hos-halt` | S-A: unchanged. S-B: **widens** (nested copies). | S-A: **NARROWS** (`n/docs/AGENTS.md` etc.). S-B: unchanged. | No tracked nested copy exists today except under `prompts/`. |
| P3 no-slash exact file | `AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md`, `.hos-release` | S-A and S-B: **widen** to any depth (gains `templates/AGENTS.md`, `prompts/AGENTS.md`). S-A also matches suffix lookalikes (F5). | S-A and S-B: unchanged for real nesting. S-A adds suffix lookalikes. | Consumer impact: F9. |
| P4 `**/<dir>/**` | `**/auth/**`, `**/authn/**`, `**/authz/**`, `**/session/**`, `**/credentials/**`, `**/secrets/**`, `**/crypto/**` (security only; CI does not consume this file) | n/a | S-A and S-B: **widen** (root-level dirs, F4). S-A additionally matches `oauth/`-style lookalikes. | |

No currently listed pattern contains a mid-pattern single `*`, `?`, `[`, `!` or a leading or trailing
`/`. The issue's `dir/*` depth divergence is therefore **latent** for both surface files, but live
for M4 (`release/v*`, `CHANGELOG*`; ESC-4).
Allow-direction lists (measured): `release_panel_exclusions.txt` and `audit_allowlist.txt` produce
identical match sets under M1, M2 and M3 on today's tree. But `SCRIPTS-INDEX.md` and `.hos-manifest`
in the exclusions are no-slash entries. Under any-depth semantics they would start excluding nested
same-named files from release review. → ESC-6.

**F7 — CODEOWNERS is generated root-anchored.** `gen_codeowners.sh` maps `dir/**`→`/dir/` and every
other line to `/<line>`. So `AGENTS.md` becomes `/AGENTS.md` (root only), while M2/S-B treat the
source line as any-depth. Under S-B, CODEOWNERS would be narrower than the CI gate for P1–P3 nested
copies. GitHub's real CODEOWNERS behaviour is the only external ground truth in the system. It is
not executable here, so it must be represented by a hand-written oracle table. → REQ-U6, ESC-3.

**F8 — Consumer shipping.**
- **Shipped and overwritten on every install** (`cp_framework_file` is an unconditional `cp`):
  `require_human_approval.py`, `protected_surfaces.txt`, `gen_codeowners.sh` and the workflow
  (`framework_consumer_files.txt`); `scripts/oversight/` as a whole (so M2) via rsync.
- **Not shipped:** `scripts/automation/` (M3, M4, M5), `security_surfaces.txt`, `audit_predicate.py`.
- A consumer's protected list is HOS's list, and local edits are clobbered.
- If M1 is changed to load a new sibling module and that module is not added to
  `framework_consumer_files.txt`, every consumer's required `require-human-approval` check errors
  and **blocks every consumer PR**. → REQ-U5.

**F9 — Consumer behaviour change.** Under S-A or S-B, the P3 lines (`AGENTS.md`, `CLAUDE.md`,
`METHODOLOGY.md`, `.hos-release`) protect nested copies in consumer repos. A monorepo with
`packages/*/CLAUDE.md` would gain human-gated PRs. That is arguably correct, because nested
`CLAUDE.md` files are agent-instruction files, but it raises gate load. → ESC-7.

**F10 — Fail behaviour differs, and one gap is fail-open.**
- M1 exits 2 on a missing list.
- M3 returns True (protected) on a read exception, but returns **False** when
  `protected_surfaces.txt` is absent. The security variant documents that choice; the protected
  variant does not.
- Every other caller fails closed or raises (`release_panel_logic.load_exclusions` raises
  `FileNotFoundError`). → REQ-U4, ESC-5.

**F11 — Trusted-base constraint.** The CI gate runs `python3 scripts/framework/require_human_approval.py`
from `actions/checkout` pinned to `base.sha` (`test_gate_checkout_pins_base_sha`, #972). The sanctioned
way to share code into it is `importlib` by sibling file path with no `sys.path` mutation
(`require_overseer_approval.py:_load_sibling_module`, `audit_predicate.py:_load_sibling_module`).
`release_panel_logic.py` mutates `sys.path` to import M1. That is acceptable there (it is not a
trusted-base gate), but it is a second import idiom.

## 3. Requirements

### Semantics

**REQ-U1 — One matcher module, one grammar, defined once.** Exactly one module in
`scripts/framework/` defines the surface-glob grammar and its translation. "One" is enforced by
REQ-U8. The grammar is GitHub CODEOWNERS path semantics, with these properties:
- **Separators and anchoring.**
  - A leading `/` anchors at the repo root and is stripped.
  - A trailing `/` means the directory and everything under it.
  - A pattern with no `/` (other than a trailing one) matches at any depth.
  - A pattern containing a `/` is root-anchored.
- **Wildcards.**
  - `*` matches within one segment only.
  - `**/` matches zero or more whole directories, never a name suffix (fixes F5: `**/auth/**` does
    not match `oauth/x`; `AGENTS.md` does not match `NOTAGENTS.md`).
  - A trailing `/**` matches everything under the directory, but not the directory path itself.
- **Case.** Matching is case-sensitive.
- **Unsupported syntax.** `!`, `[`, `]`, `?` and `\` are rejected at load (REQ-U4). Silent literal
  treatment is not allowed.
- **Input paths.** Path input is normalized once: strip surrounding whitespace, then a leading `./`
  or `/`. An empty path never matches and is skipped.

The grammar is stated in the module docstring, in the header of every pattern file it reads, and in
the DECISIONS.md entry (REQ-U7).

**REQ-U2 — No protection narrowing without a human ruling.** For every deny-direction caller (the CI
gate, `touches_protected_surface`, `touches_security_surface`, the CODEOWNERS-human-owned check, and
M4 if ESC-4 brings it in), the new match set for each currently listed pattern must be a
**superset** of that caller's current match set. This holds on the real tree and on the F6 probe
set. The only exceptions are the F5 suffix-lookalike over-matches, which never were GitHub
semantics; ESC-1 asks the human to accept dropping them. Any other narrowing (including all of F3
under S-A) is permitted only after an explicit human ruling under ESC-1, and is then recorded in
DECISIONS.md with the exact lost paths.

**REQ-U3 — Allow-direction callers must not widen.** For `release_panel_logic.apply_exclusions` and
the `audit_predicate` allowlist, the new match set for each currently listed pattern must be a
**subset** of the current one. The required result is that release-review coverage and
audit-bot auto-approval do not grow silently. How it is achieved is ESC-6.

**REQ-U4 — Fail-closed is preserved, never weakened.**
- Deny-direction callers:
  - an unreadable list, or a list containing a rejected pattern, means **protected** (M3 returns
    True; the CI gate exits 2, never 0 or 1);
  - an internal exception never yields "not protected".
- Allow-direction callers: the same conditions mean **nothing is allowed** (exclusion raises; the
  audit predicate returns not-an-audit-PR).
- A missing `protected_surfaces.txt` in M3 is decided by ESC-5. Until that is ruled, today's
  behaviour is unchanged.

### Placement and wiring

**REQ-U5 — The trusted-base CI gate keeps its guarantees.**
- `require_human_approval.py` loads the module by sibling file path, without mutating `sys.path`.
- The workflow still checks out `base.sha`.
- `tests/framework/test_gate_checkout_pinned_base.py` passes unchanged.
- The new module lives under `scripts/framework/`, so it is on the protected surface. A PR that edits
  the matcher is human-gated by the matcher already on base.
- The module is added to `framework_consumer_files.txt` (and therefore to `.hos-manifest`) in the
  **same PR** that makes `require_human_approval.py` depend on it. A test asserts that every sibling
  module loaded by a shipped `scripts/framework/*.py` gate is itself in the ship-set (F8).

**REQ-U6 — CODEOWNERS is in the equivalence set.**
- `gen_codeowners.sh` must emit, for each protected pattern, CODEOWNERS lines whose
  **GitHub-semantics** match set equals the CI gate's match set for that pattern. The residual
  differences ruled acceptable under ESC-3 are the only exception.
- `regen_all.sh --check` must pass after regeneration.
- `.github/CODEOWNERS` is regenerated in the same PR, and it is a protected surface.

**REQ-U7 — Decision recorded.** A DECISIONS.md entry, appended at the bottom, records:
- the chosen grammar (REQ-U1);
- the ESC-1 option;
- every pattern whose match set changed for any caller, with direction (widen/narrow) and the
  tracked paths gained or lost;
- the ESC-2/4/5/6/7 rulings;
- the #559 relationship.

The header comments of `protected_surfaces.txt` and `security_surfaces.txt` are corrected to the
chosen semantics (F2).

### Tests

**REQ-U8 — One definition repo-wide.** A grep test over `scripts/`, `bootstrap/` and `bin/` asserts:
- exactly one `def glob_to_regex` (or equivalent translator);
- no `fnmatch` use for surface matching in `merge_authority.py`.

M5 is exempt only if ESC-2 keeps it, and then by name.

**REQ-U9 — Table-driven cross-caller equivalence test.**
- **Coverage.** One table of (pattern, path, expected) rows covers:
  - every F6 class;
  - every current pattern in both surface files, the exclusions and the allowlist;
  - the edge cases: no-slash at root, one-deep and deep; `dir/*` one versus many segments; leading
    `/`; trailing `/`; `**/` at the root; suffix and prefix lookalikes (`NOTAGENTS.md`, `oauth/x`,
    `scripts/oversight-adjacent/x`); `./` and leading-`/` input paths; empty path; rejected syntax.
- **Expected values.** The `expected` column is a hand-written **GitHub CODEOWNERS oracle**, cited to
  GitHub's documented examples where one exists. It is not computed by any implementation under test.
- **Callers run.** Every caller entry point runs the table: `matched_surfaces`,
  `touches_protected_surface`, `touches_security_surface`, `codeowners.get_owners_for_path` (over a
  generated CODEOWNERS fixture) and `apply_exclusions`, plus the `gen_codeowners.sh` translation.
  For mode-specific rows (ESC-1 (B)), the expected value is stated per mode.
- **Real-tree check.** A second test computes each deny-direction caller's match set over
  `git ls-files` and asserts the REQ-U2 superset relation against a committed snapshot of today's
  sets. The snapshot is taken before the change. It is updated only alongside a DECISIONS.md entry.

**REQ-U10 — Existing pins.**
- These keep passing:
  - `tests/framework/test_require_human_approval.py` (including `test_near_misses_do_not_match`);
  - `tests/oversight/test_codeowners.py`;
  - `tests/automation/test_phase_b.py` (`TestKnownDivergenceFromOversightCodeowners` stays unless
    ESC-2 retires M5, which requires the architect sign-off the test itself demands);
  - `tests/oversight/test_release_panel_logic.py`;
  - `scripts/framework/run_tests_inner_loop.sh`.
- A pinned row may change only where a DECISIONS-recorded ruling changed that behaviour, and the PR
  names each changed row.

## 4. Out of scope / non-goals

- Adding, removing or re-scoping any pattern in either surface file (beyond the ESC-4/ESC-6
  rewrites that preserve a match set). Fixing the stale `AGENT-IDENTITY.md` §9.0 list (F2).
- Shipping `scripts/automation/` or `security_surfaces.txt` to consumers (F8). Consumer
  customisation of the protected list (consumer edits are clobbered today).
- Changing reviewer-routing, tiering or the merge-authority matrix. Only the surface predicate
  changes.
- Retiring M5. This is named by ESC-2 and would be a separate issue.

## 5. Acceptance criteria

- **AC-1** `grep -rn "def glob_to_regex" scripts bootstrap bin` returns exactly one hit. There is no
  `fnmatch` in surface matching (REQ-U8).
- **AC-2** The equivalence table (REQ-U9) passes for every caller. It includes
  `oauth/x` ↛ `**/auth/**`, `auth/x` → `**/auth/**`, `NOTAGENTS.md` ↛ `AGENTS.md`, and
  `docs/sub/AGENTS.md` → `AGENTS.md`.
- **AC-3** The real-tree superset test passes for every deny-direction caller against the
  pre-change snapshot. Under ESC-1 (A), the listed narrowed paths appear in DECISIONS.md and
  nowhere else silently (REQ-U2).
- **AC-4** The allow-direction subset test passes: exclusions and allowlist match no new tracked
  path (REQ-U3).
- **AC-5** These cases fail closed (REQ-U4):
  - an unreadable `protected_surfaces.txt` → `touches_protected_surface` returns True and the CI
    gate exits 2;
  - a list line `src/[ab].py` → both treat it as protected or error;
  - `apply_exclusions` raises.
- **AC-6** `test_gate_checkout_pinned_base.py` passes unchanged. `require_human_approval.py` has no
  `sys.path` mutation (grep). The new module appears in `framework_consumer_files.txt`, and the
  ship-set sibling test passes (REQ-U5).
- **AC-7** `gen_codeowners.sh` output satisfies the REQ-U6 oracle rows. `regen_all.sh --check`
  passes (REQ-U6).
- **AC-8** A DECISIONS.md entry exists, and both pattern-file headers state the grammar (REQ-U7).
- **AC-9** Every REQ-U10 suite passes.

## 6. Escalations — human decisions required (recommended default for each)

**ESC-1 — Which semantics, and is any narrowing accepted?**
- **(A)** M2 semantics everywhere (the issue's recommendation), with the F5 fix. This **narrows the
  overseer** by 5 protected and 6 security tracked files (all `prompts/` mirrors), and by every
  future nested copy of a P1/P2 pattern (F3, F6).
- **(B)** One module, one grammar (REQ-U1), two named modes:
  - `protect` = grammar plus a nested-anywhere fallback, preserving OV's behaviour, for every
    deny-direction caller;
  - `exact` = grammar only, for CODEOWNERS ownership modelling and allow-direction callers.

  Nothing narrows. The CI gate widens to the overseer's set (F3), so the 7 `prompts/` and
  `templates/AGENTS.md` files become red in CI without human approval. They are already
  HUMAN_REQUIRED at the overseer, so this adds no new human work.
- **(C)** (A) for the CI gate and CODEOWNERS, and keep M3's fallback in the overseer. That is not a
  unification, and it leaves the disagreement the issue is about.

**Recommended: (B).** It is the only option that satisfies REQ-U2 without a ruling. It also matches
the #559 finding that deny- and allow-direction callers need opposite failure biases, so one grammar
with an explicit, named mode is honest about that. Either way, the human is asked to accept dropping
the F5 suffix-lookalike over-matches (`NOTAGENTS.md`, `oauth/x`). Those were never GitHub semantics,
and no tracked file is affected.

**ESC-2 — M5 (`scripts/automation/lib/codeowners.py`).** It has no production callers, and its
divergence is pinned by an architect ruling (#559). **Recommended:** exempt it by name from REQ-U8
here, and open a separate issue to retire it. Folding it in would override #559 and needs the
architect sign-off the pinned test demands.

**ESC-3 — CODEOWNERS fidelity.** Under (B), the CI gate covers nested copies, and CODEOWNERS can
express them only by emitting extra `**/<p>` lines. These would make GitHub require code-owner
review on `prompts/…` mirrors too. **Recommended:** emit no-slash patterns unanchored (GitHub's
any-depth, now equal to the CI gate). Do not emit nested-fallback lines. Accept and record
"CODEOWNERS ⊆ CI gate" for nested P1/P2 copies, because the CI gate is the load-bearing dynamic
half. The alternative is full equality via `**/` lines.

**ESC-4 — M4, the release-path matcher.** It is a fifth matcher the issue missed. It is
case-insensitive, and its `*` crosses `/` (`release/v*` matches `release/v1/a/b`). **Recommended:**
in scope, in `protect` mode, with case-insensitivity kept as an explicit per-call option. Rewrite
the list entries so that no match is lost (for example `release/v*` plus `release/v*/**`).
Alternative: leave M4 out and exempt it by name.

**ESC-5 — Missing `protected_surfaces.txt` makes the overseer return "not protected" (F10).**
**Recommended:** change it to protected (fail-closed), matching the CI gate's exit 2. This only
tightens behaviour. Keep the security variant's documented "missing = not relevant", because the
protected list covers its file.

**ESC-6 — Allow-direction no-slash entries (F6).** `SCRIPTS-INDEX.md` and `.hos-manifest` in the
release exclusions would, under the any-depth grammar, exclude nested same-named files from release
review. **Recommended:** anchor them in the list (`/SCRIPTS-INDEX.md`, `/.hos-manifest`). That keeps
one grammar and leaves today's match set identical. The alternative is a mode in which no-slash
means root-only.

**ESC-7 — Consumer widening (F9).** Nested `AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md` and
`.hos-release` become protected in consumer repos. **Recommended:** accept, and state it in the
release notes as a behaviour change.

## 7. Escalation flag (CORE self-flag)

RISK: HIGH. This changes the predicate behind the server-side human-approval gate, the overseer's
protected-surface and security-surface routing, and CODEOWNERS. A wrong translation silently
lets governance changes auto-merge. All touched files are protected (`scripts/framework/**`,
`.github/CODEOWNERS`) or security (`scripts/automation/lib/**`) surfaces.

CONFIDENCE: 85%.
- **High** on F1–F8 and F10: code read, and match sets measured over the full tracked tree and a
  probe set this session.
- **Medium** on the GitHub-oracle details for edge rows (trailing `/**` on the directory itself,
  `**/` at the root). Technical design must cite GitHub documentation per oracle row.

BLAST RADIUS:
- every PR's `require-human-approval` result, in HOS and in every consumer;
- the overseer's auto-merge eligibility;
- the release-review file set;
- consumer CI breakage if REQ-U5's ship-set rule is missed.

Classification: **structural**. It changes which paths existing controls treat as protected
(widening the CI gate under every option, and possibly narrowing the overseer under ESC-1 (A)). It
changes CODEOWNERS output and adds a fail-closed condition (ESC-5). None of this may be applied
without human sign-off. This document proposes the changes; it does not authorize them.

## Human Review Required

- **ESC-1** must be answered before technical design, because it decides whether the overseer's
  protected set narrows.
- **ESC-2** touches an architect ruling (#559).
- **ESC-3..ESC-7** have safe defaults that design may assume. They are not binding until the human
  confirms them.
- **F3 contradicts the issue's recommendation.** Adopting `scripts/oversight/codeowners.py`
  semantics as-is is protection-narrowing for the overseer, not neutral.
- **F4 is a live fail-open.** The overseer's security check misses repo-root `auth/`, `session/`,
  `crypto/`, `secrets/`, `credentials/`, `authn/` and `authz/`. It is fixed by any option.
- The PR is human-gated: protected surfaces and security surfaces, CODEOWNERS.
