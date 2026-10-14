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

## Revision history

- **rev 1** (2026-10-14, `f29d04d8d`): F1–F11, REQ-U1..U10, AC-1..9, ESC-1..7.
- **rev 2** (2026-10-14): applies the architect's amendments **AM-1..AM-10** from
  `docs/v0.7.0/ADR-1574-surface-matcher-unify.md` §11 (verdict: APPROVED WITH CONDITIONS).
  - AM-1: caller inventory extended; routing caller added (F1, new REQ-U11).
  - AM-2: ESC-1 (B)'s `protect`/`exact` modes struck; replaced by (B′), nesting written as `**/`
    lines in the list text; the matcher has one behaviour, no mode parameter (REQ-U1, REQ-U9, ESC-1).
  - AM-3: (B′) on the protected list widens consumers for nested P1/P2 too (F9, ESC-7, ARCH-ESC-1).
  - AM-4: lossless M4 rewrite needs `**/` forms and `CHANGELOG*/**`; case-insensitivity is caller-side
    (F6, ESC-4).
  - AM-5: the real-tree snapshot is replaced by frozen, hash-pinned legacy reference matchers (REQ-U9).
  - AM-6: `regen_all.sh --check` copies the module; the generator writes atomically; the installer
    warn-skips missing listed files, so the ship-set test is the only guard (F8, REQ-U5, REQ-U6).
  - AM-7: the CI gate exits 1, not 2, on an uncaught exception today; REQ-U4 needs a new wrapper (F10).
  - AM-8: one DECISIONS.md entry per behaviour-changing slice (REQ-U7).
  - AM-9: `?` is pending a GitHub citation (TD-O2); inline `#` and internal whitespace are rejected
    (F2, REQ-U1).
  - AM-10: no `**/` line in a surface list while a legacy matcher reads it (REQ-U2).
  - ESC/ARCH-ESC numbering follows the ADR §12: ESC-1..7 (human, pm-owned) plus ARCH-ESC-1..3.
  - pm-agent's product notes on the amendments are marked **PM note** inline. No amendment was
    dropped; the one point of disagreement (the architect's characterisation of the `prompts/`
    mirrors) is recorded at ESC-1 and does not change any requirement.

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

**F1 — There are five matchers, and more call sites than rev 1 counted.**

| # | Matcher | Algorithm | Callers (direction) |
|---|---|---|---|
| M1 | `scripts/framework/require_human_approval.py` `glob_to_regex` / `matched_surfaces` | `**`→`.*`, `*`→`[^/]*`, anchored; no normalization | CI gate (deny); `scripts/oversight/release_panel_logic.py` `apply_exclusions` via `sys.path` import (**allow**: excludes files from release review); `scripts/framework/audit_predicate.py` via `_load_sibling_module` (**allow**: audit-bot path allowlist); tests |
| M2 | `scripts/oversight/codeowners.py` `glob_to_regex` | M1 + strip leading `/`, trailing `/`→`/**`, no-slash→`**/<p>` (#975) | `check_pr_files` / `get_owners_for_path` → overseer CODEOWNERS-human-owned gate (deny), via `merge_authority_cli.py` and `pr_review_cli.py`; `get_owners_for_path` → `resolve_human_reviewer` (`pr_review_cli.py:1034`) (**routing**: picks which human to request; last-match-wins sensitive) (AM-1) |
| M3 | `scripts/automation/lib/merge_authority.py` `touches_protected_surface`, `touches_security_surface` | `fnmatch(f,p) or fnmatch(f,"**/"+p)`; fnmatch `*` crosses `/` | `decide_merge_authority`; `merge_authority_cli.py` (including per file at `:601`); `pr_review_cli.py` (including `:1165`); `pr_review_cli.evaluate_reviewer_trigger` (`:915`, ADR-1657 AD-3) (all deny) (AM-1) |
| M4 | same file, `_matches_release_path` over `_RELEASE_PATH_GLOBS` | M3 algorithm, **case-insensitive**, strips `./` | NG3b release detection (deny). **Not named in the issue.** |
| M5 | `scripts/automation/lib/codeowners.py` `_fnmatch_codeowners` | escape, `**`→`.*`, `*`→`[^/]*`, suffix `(/.*)?`; root-anchored | `actor_is_codeowner` — **no production callers** (module docstring). Divergence from M2 is pinned on purpose by the #559 architect ruling ("A shared matcher cannot serve both" — opposite fail directions; `TestKnownDivergenceFromOversightCodeowners`, "must NOT be deleted or fixed"). |

Two of M1's callers use a match to **allow** something (skip release review; let the audit bot
approve). For them an over-match is the dangerous direction. The issue frames every caller as a
deny-direction gate, and that is not true. → REQ-U3, ESC-6.

A third direction exists: `resolve_human_reviewer` **routes**. It is neither allow nor deny, and
REQ-U2/U3 do not classify it (AM-1). → REQ-U11. Because `get_owners_for_path` keeps the **last**
matching entry, an over-match there can move a human-owned path to a non-human owner (ADR AF-2). So
an over-match is not safe in CODEOWNERS resolution even for the deny-direction `check_pr_files`.

**F2 — The pattern-file headers contradict the code.**
- `protected_surfaces.txt` says "a plain path = that exact file". That is true of M1 (root-only),
  but M3 also matches it at any depth, and under M2 semantics a no-slash plain path matches at any
  depth.
- `security_surfaces.txt` says "every pattern is also checked nested under any directory via a
  `**/<pattern>` fallback". That is true only of M3.
- `docs/AGENT-IDENTITY.md` §9.0 calls the list "canonical glob paths" without defining a dialect.
  Its copy of the list is also stale (no `bin/**`, `PROJECT/*`, `templates/CLAUDE.human.md`,
  `docs/releases/**`, `.hos-release`). That staleness is out of scope here (ADR FU-4).
- **Parser divergence (AM-9, ADR AF-7).** `gen_codeowners.sh` strips inline `#` comments, but
  `load_globs` and M3 do not. A line `bin/** # tools` would generate a correct CODEOWNERS line while
  the CI gate compiled a literal that never matches, which is fail-open. No such line exists today.

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
human gate, these narrowings are security regressions unless a human rules otherwise. → ESC-1.
(Architect re-measured and confirmed: ADR §0 row 5.)

**F4 — M3 misses root-level security directories (a live fail-open).** `**/auth/**` under fnmatch
compiles to "something, `/auth/`, something", so `auth/login.py`, `session/x`, `crypto/x`,
`secrets/x`, `credentials/x`, `authn/x` and `authz/x` at the **repo root** are *not*
security-relevant to the overseer today. M1 and M2 do match them. No tracked HOS file is affected.
A consumer app with a root `auth/` would be affected, if consumers received this check (they do
not; see F8). Any unified semantics fixes this, and the fix only widens protection. The same
mechanism makes a premature `**/` line in a list fail-open at the overseer (AM-10, REQ-U2).

**F5 — M1/M2 `**/` is defective: it eats the separator.** `**/x` compiles to `^.*x$`, so:
- `**/auth/**` matches `oauth/x`, `osession/x`, `ocrypto/x`;
- M2's no-slash normalization makes `AGENTS.md` match `NOTAGENTS.md`, `CLAUDE.md` match
  `NOTCLAUDE.md`, and `.hos-release` match `NOT.hos-release`.

GitHub's `**/x` means x at the root or under any directory, never as a name suffix. M2's claim to
model GitHub is therefore wrong in the over-match direction. Rev 1 called this harmless for
deny-direction callers; that is corrected by F1's last-match-wins note: inside CODEOWNERS
resolution it is a latent fail-open in the model (GitHub still enforces CODEOWNERS server-side, so
the effect is a wasted auto-merge attempt, not a bypass). It would also be dangerous for
allow-direction callers once they share the module.

**F6 — Per-pattern effect of unification.** All 22 protected and 8 security patterns fall into four
classes. "CI" is M1, "OV" is M3, and "CO" is M2 applied as the CODEOWNERS model. **S-A** is ESC-1
(A): the GitHub grammar (REQ-U1) applied to the lists as written. **S-B** is ESC-1 (B′): the same
grammar, with the affected lines rewritten in the list as `**/<p>` (AM-2). There is one matcher in
both cases; only the list text differs.

| Class | Patterns | vs CI today | vs OV today | Notes |
|---|---|---|---|---|
| P1 slash-containing `dir/**` | `.claude/agents/**`, `contract/**`, `bin/**`, `bootstrap/**`, `scripts/framework/**`, `scripts/oversight/gates/**`, `.github/workflows/**`, `docs/releases/**`, `scripts/automation/lib/**` (security) | S-A: unchanged. S-B: **widens** (nested copies, e.g. `prompts/bin/hos-cron.md`). | S-A: **NARROWS** (nested copies lost). S-B: unchanged. | S-B widening reaches consumers (AM-3, ARCH-ESC-1). |
| P2 slash-containing exact file | `templates/CLAUDE.human.md`, `docs/AGENTS.md`, `docs/AGENT-IDENTITY.md`, `docs/FABERIX-ROLES.md`, `docs/CROSS-REPO-CONDUCT.md`, `scripts/oversight/run_validators.sh`, `scripts/oversight/validators/schema.py`, `.github/CODEOWNERS`, `PROJECT/hos-coordination.yaml`, `PROJECT/hos-halt` | S-A: unchanged. S-B: **widens** (nested copies). | S-A: **NARROWS** (`n/docs/AGENTS.md` etc.). S-B: unchanged. | No tracked nested copy exists today except under `prompts/`. |
| P3 no-slash exact file | `AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md`, `.hos-release` | S-A and S-B: **widen** to any depth (gains `templates/AGENTS.md`, `prompts/AGENTS.md`). | Unchanged for real nesting. Legacy M2 suffix lookalikes are dropped (F5). | Consumer impact: F9. |
| P4 `**/<dir>/**` | `**/auth/**`, `**/authn/**`, `**/authz/**`, `**/session/**`, `**/credentials/**`, `**/secrets/**`, `**/crypto/**` (security only; CI does not consume this file) | n/a | S-A and S-B: **widen** (root-level dirs, F4). Legacy `oauth/`-style lookalikes are dropped (F5). | |

No currently listed pattern contains a mid-pattern single `*`, `?`, `[`, `!` or a leading or trailing
`/`. The issue's `dir/*` depth divergence is therefore **latent** for both surface files, but live
for M4 (`release/v*`, `CHANGELOG*`; ESC-4). Correction (AM-4): under M4, `CHANGELOG*` also matches
`CHANGELOG.d/x` and `x/CHANGELOG.d/y`, so a lossless rewrite needs `**/CHANGELOG*/**` as well as the
`**/` forms.
Allow-direction lists (measured): `release_panel_exclusions.txt` and `audit_allowlist.txt` produce
identical match sets under M1, M2 and M3 on today's tree. But `SCRIPTS-INDEX.md` and `.hos-manifest`
in the exclusions are no-slash entries. Under any-depth semantics they would start excluding nested
same-named files from release review. → ESC-6.

**F7 — CODEOWNERS is generated root-anchored.** `gen_codeowners.sh` maps `dir/**`→`/dir/` and every
other line to `/<line>`. So `AGENTS.md` becomes `/AGENTS.md` (root only), while the REQ-U1 grammar
treats the source line as any-depth. GitHub's real CODEOWNERS behaviour is the only external ground
truth in the system. It is not executable here, so it must be represented by a hand-written oracle
table. → REQ-U6, ESC-3.

**F8 — Consumer shipping.**
- **Shipped and overwritten on every install** (`cp_framework_file` is an unconditional `cp`):
  `require_human_approval.py`, `protected_surfaces.txt`, `gen_codeowners.sh` and the workflow
  (`framework_consumer_files.txt`); `scripts/oversight/` as a whole (so M2) via rsync.
- **Not shipped:** `scripts/automation/` (M3, M4, M5), `security_surfaces.txt`, `audit_predicate.py`.
- A consumer's protected list is HOS's list, and local edits are clobbered.
- If M1 is changed to load a new sibling module and that module is not added to
  `framework_consumer_files.txt`, every consumer's required `require-human-approval` check errors
  and **blocks every consumer PR**. → REQ-U5.
- **Installer gap (AM-6).** `hos_install.sh` *warns and skips* a listed file that is missing from
  the source. A missing module therefore ships a broken required check with **no install failure**.
  The ship-set test (REQ-U5) is the only guard. Fixing the installer is ADR FU-2, out of scope here.
- **Regen gap (AM-6).** `regen_all.sh --check` regenerates CODEOWNERS in a temp tree that contains
  only `gen_codeowners.sh` and the list. If the generator depends on the module, the check goes
  permanently red. → REQ-U6.

**F9 — Consumer behaviour change.** Under S-A or S-B, the P3 lines (`AGENTS.md`, `CLAUDE.md`,
`METHODOLOGY.md`, `.hos-release`) protect nested copies in consumer repos. A monorepo with
`packages/*/CLAUDE.md` would gain human-gated PRs. That is arguably correct, because nested
`CLAUDE.md` files are agent-instruction files, but it raises gate load. → ESC-7.
**Added by AM-3:** under S-B applied to `protected_surfaces.txt`, the consumer CI gate (and
CODEOWNERS) also widens for every nested P1/P2 directory — `**/bin/**`, `**/bootstrap/**`,
`**/contract/**`, `**/scripts/framework/**`, `**/.github/workflows/**`, `**/docs/releases/**` and
similar. In a Node or Python monorepo `packages/*/bin/` is ordinary. This consumer gate load is
unmeasured. → ARCH-ESC-1. `security_surfaces.txt` is not shipped, so S-B on that list has no
consumer effect.

**F10 — Fail behaviour differs, and two gaps are fail-open or misreported.**
- M1 exits 2 on a missing list. **Correction (AM-7):** M1 has no top-level exception handler, so any
  uncaught exception (for example a future module-load failure) exits **1**, which reads as
  "protected, no human approval", not "tooling error".
- M3 returns True (protected) on a read exception, but returns **False** when
  `protected_surfaces.txt` is absent. The security variant documents that choice; the protected
  variant does not (`merge_authority_cli.py` discloses it only as "the library's permissive default").
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

**REQ-U1 — One matcher module, one grammar, defined once, no modes.** Exactly one module in
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
- **Case.** Matching is case-sensitive. A caller that needs case-insensitive matching (M4) lowercases
  its own input; the module has no case option (AM-4).
- **Unsupported syntax.** `!`, `[`, `]` and `\` are rejected at load (REQ-U4). Silent literal
  treatment is not allowed. **`?` is pending (AM-9):** technical-design must cite GitHub on `?`
  (TD-O2). If GitHub supports it, the grammar implements `?` as one non-`/` character; if not, it is
  rejected. Until TD-O2 resolves, `?` is rejected.
- **Line syntax (AM-9).** Blank lines and full-line `#` comments are skipped. An inline `#` or any
  internal whitespace in a pattern line is rejected (REQ-U4), not guessed at. The module owns the
  single line parser; the CODEOWNERS generator and every list caller use it (F2).
- **Input paths.** Path input is normalized once: strip surrounding whitespace, then a leading `./`
  or `/`. An empty path never matches and is skipped.
- **No mode parameter (AM-2; architect's technical ruling, ADR AD-1/AD-2).** The matching semantics
  are identical for every caller. Callers differ only in what they do on an **error** (REQ-U4).
  Nesting that a list wants ("this directory wherever it appears") is written explicitly in the list
  text as a `**/` line; the matcher never adds an implicit nested fallback.

The grammar is stated in the module docstring, in the header of every pattern file it reads, and in
the DECISIONS.md entries (REQ-U7).

**REQ-U2 — No protection narrowing without a human ruling.** For every deny-direction caller (the CI
gate, `touches_protected_surface`, `touches_security_surface`, the CODEOWNERS-human-owned check, and
M4 if ESC-4 brings it in), the new match set for each currently listed pattern must be a
**superset** of that caller's current match set. This holds on the real tree and on the F6 probe
set. The only exceptions are the F5 suffix-lookalike over-matches, which never were GitHub
semantics; ESC-1 asks the human to accept dropping them. Any other narrowing (including all of F3
under ESC-1 (A)) is permitted only after an explicit human ruling under ESC-1, and is then recorded
in DECISIONS.md with the exact lost paths.
- **Ordering constraint (AM-10).** No `**/`-prefixed line may be added to `protected_surfaces.txt` or
  `security_surfaces.txt` while either legacy matcher (M1 or M3) still reads that list. Legacy M3
  does not match root paths for `**/x/**` (the F4 mechanism), so `**/bin/**` would stop protecting
  `bin/hos-cron` at the overseer; legacy M1 compiles it to a pattern that matches `robin/x`. Such a
  rewrite lands in the same PR as, or after, the last caller of that list moves to the new module
  (ADR AD-9 (a)).

**REQ-U3 — Allow-direction callers must not widen.** For `release_panel_logic.apply_exclusions` and
the `audit_predicate` allowlist, the new match set for each currently listed pattern must be a
**subset** of the current one. The required result is that release-review coverage and
audit-bot auto-approval do not grow silently. How it is achieved is ESC-6.

**REQ-U4 — Fail-closed is preserved, never weakened.**
- Deny-direction callers:
  - an unreadable list, or a list containing a rejected pattern or line, means **protected** (M3
    returns True; the CI gate exits 2, never 0 or 1);
  - an internal exception never yields "not protected". For the CI gate this requires a **new**
    top-level wrapper in `main` that turns any uncaught exception (including a module-load
    failure) into exit 2; preserving today's behaviour is not enough, because today it exits 1
    (AM-7, F10).
- Allow-direction callers: the same conditions mean **nothing is allowed** (exclusion raises; the
  audit predicate returns not-an-audit-PR).
- The CODEOWNERS model on a CODEOWNERS line the grammar rejects is decided by ARCH-ESC-2. A
  routing caller never guesses an owner on such a line (REQ-U11).
- A missing `protected_surfaces.txt` in M3 is decided by ESC-5. Until that is ruled, today's
  behaviour is unchanged.

### Placement and wiring

**REQ-U5 — The trusted-base CI gate keeps its guarantees.**
- `require_human_approval.py` loads the module by sibling file path, without mutating `sys.path`.
- The workflow still checks out `base.sha`.
- `tests/framework/test_gate_checkout_pinned_base.py` passes unchanged.
- The new module lives under `scripts/framework/`, so it is on the protected surface. A PR that edits
  the matcher is human-gated by the matcher already on base.
- The module is added to `framework_consumer_files.txt` (and therefore to `.hos-manifest`) **no later
  than** the PR that makes `require_human_approval.py` depend on it. The architect's plan ships it
  earlier, in the PR that introduces the module (ADR AD-6, S1); that is stricter and accepted.
- A test asserts that every module loaded by file path from a shipped `scripts/framework/*.py` or
  any `scripts/oversight/*.py` is itself in the ship-set (F8). Because the installer warn-skips a
  missing listed file (F8, AM-6), this test is the **only** guard against shipping a broken required
  check; it must fail on a non-literal load target rather than skip it.

**REQ-U6 — CODEOWNERS is in the equivalence set.**
- `gen_codeowners.sh` must emit, for each protected pattern, CODEOWNERS lines whose
  **GitHub-semantics** match set equals the CI gate's match set for that pattern. The residual
  differences ruled acceptable under ESC-3 are the only exception. The generator refuses (exit 2)
  any pattern shape it cannot prove equal.
- `regen_all.sh --check` must pass after regeneration. Its temp tree must contain the module
  (AM-6, F8).
- The generator writes `.github/CODEOWNERS` atomically: a failure mid-generation leaves the
  committed file byte-identical, never truncated (AM-6).
- `.github/CODEOWNERS` is regenerated in the same PR, and it is a protected surface.

**REQ-U7 — Decisions recorded, one entry per behaviour-changing slice (AM-8).** Each slice that
changes any caller's match set or fail behaviour appends its own DECISIONS.md entry, at the bottom,
before or with its change. Each entry records:
- the grammar identifier (REQ-U1);
- every pattern whose match set that slice changed for any caller, with direction (widen/narrow)
  and the tracked paths gained or lost;
- the human rulings that slice depends on (ESC-1..7, ARCH-ESC-1..3 as applicable);
- for the overseer slice, the ESC-1 option and the #559 relationship.

A single up-front entry is not allowed: it would precede rulings it cannot know, or postdate
behaviour changes it should gate.

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
    `scripts/oversight-adjacent/x`); `./` and leading-`/` input paths; empty path; rejected syntax;
    inline `#` and internal whitespace (AM-9).
- **Expected values.** The `expected` column is a hand-written **GitHub CODEOWNERS oracle**, cited to
  GitHub's documented examples where one exists. It is not computed by any implementation under test.
  Rows whose GitHub behaviour is not yet cited (ADR TD-O1, TD-O2) are marked unknown, not guessed.
- **Callers run.** Every caller entry point runs the table: `matched_surfaces`,
  `touches_protected_surface`, `touches_security_surface`, `codeowners.get_owners_for_path` (over a
  generated CODEOWNERS fixture), `resolve_human_reviewer` (REQ-U11), `apply_exclusions`, the
  `audit_predicate` allowlist rule, and `_matches_release_path` if ESC-4 brings M4 in, plus the
  `gen_codeowners.sh` translation. A caller not yet wired is listed as pending, never silently
  skipped. The expected value is stated **per list text**, not per mode (AM-2): a `**/<p>` line and
  a `<p>` line are separate rows.
- **Real-tree check (AM-5).** A second test evaluates, on the live `git ls-files` tree plus the F6
  probe set at test time, each caller's new match set against **frozen legacy reference matchers**:
  verbatim copies of M1–M4 as of `cf1ca09ee`, kept under `tests/`, with each copy's source hash
  pinned so it cannot drift. Deny callers: new ⊇ legacy. Allow callers: new ⊆ legacy. Ruled
  exceptions are expressed as predicates that each cite their DECISIONS.md entry, not as path
  lists. A failure prints the offending paths. (This replaces rev 1's committed path snapshot, which
  would go red on any later legitimate deletion or rename of a protected file.)

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

**REQ-U11 — Routing callers resolve the owner GitHub would (AM-1).** For `resolve_human_reviewer`,
the resolved owner for every oracle row equals GitHub's, under last-match-wins. On a CODEOWNERS line
the grammar rejects, it never returns a guessed owner; its fallback is decided with ARCH-ESC-2
(recommended: fall back to the configured human reviewer, with a note).

## 4. Out of scope / non-goals

- Adding, removing or re-scoping any pattern in either surface file, beyond the ESC-1 (B′), ESC-4
  and ESC-6 rewrites the human rules on. Fixing the stale `AGENT-IDENTITY.md` §9.0 list (F2; ADR
  FU-4).
- Shipping `scripts/automation/` or `security_surfaces.txt` to consumers (F8). Consumer
  customisation of the protected list (consumer edits are clobbered today).
- Changing `hos_install.sh`'s warn-and-skip on a missing listed file (ADR FU-2).
- Changing reviewer-routing policy, tiering or the merge-authority matrix. Only the surface predicate
  changes.
- Retiring M5. This is named by ESC-2 and would be a separate issue (ADR FU-1).
- Adding `packs/**` or `prompts/**` to a surface list (ADR FU-3; PM note at ESC-1).

## 5. Acceptance criteria

- **AC-1** `grep -rn "def glob_to_regex" scripts bootstrap bin` returns exactly one hit. There is no
  `fnmatch` in surface matching (REQ-U8). The module exposes no mode parameter (REQ-U1).
- **AC-2** The equivalence table (REQ-U9) passes for every caller. It includes
  `oauth/x` ↛ `**/auth/**`, `auth/x` → `**/auth/**`, `NOTAGENTS.md` ↛ `AGENTS.md`, and
  `docs/sub/AGENTS.md` → `AGENTS.md`. A list line with an inline `#` is rejected.
- **AC-3** The legacy-relation test (REQ-U9, AM-5) passes for every caller: deny ⊇ legacy, allow ⊆
  legacy, on the live tree. Under ESC-1 (A), the narrowed paths are covered only by a ruled
  exception predicate that cites a DECISIONS.md entry listing them (REQ-U2). No `**/` line appears
  in a surface list while a legacy matcher reads it (REQ-U2 ordering).
- **AC-4** The allow-direction subset relation holds: exclusions and allowlist match no new tracked
  path (REQ-U3).
- **AC-5** These cases fail closed (REQ-U4):
  - an unreadable `protected_surfaces.txt` → `touches_protected_surface` returns True and the CI
    gate exits 2;
  - a list line `src/[ab].py` → both treat it as protected or error, `apply_exclusions` raises, and
    the audit predicate does not qualify the PR;
  - an uncaught exception in the CI gate, including a missing or unloadable module, → exit 2
    (AM-7);
  - a CODEOWNERS line the grammar rejects → the behaviour ARCH-ESC-2 rules.
- **AC-6** `test_gate_checkout_pinned_base.py` passes unchanged. `require_human_approval.py` has no
  `sys.path` mutation (grep). A hostile `surface_glob.py` on cwd or `PYTHONPATH` is not loaded by
  the gate. The new module appears in `framework_consumer_files.txt`, and the ship-set test passes
  (REQ-U5).
- **AC-7** `gen_codeowners.sh` output satisfies the REQ-U6 oracle rows. `regen_all.sh --check`
  passes with the generator depending on the module. A failing generation leaves
  `.github/CODEOWNERS` byte-identical (REQ-U6).
- **AC-8** Each behaviour-changing slice has its own DECISIONS.md entry, and both pattern-file
  headers state the grammar (REQ-U7).
- **AC-9** Every REQ-U10 suite passes.
- **AC-10** `resolve_human_reviewer` returns GitHub's owner for every oracle row, including the
  last-match-wins row (`/scripts/ @human`, later `docs @bot`: `scripts/mydocs` → `@human`)
  (REQ-U11).

## 6. Escalations — human decisions required

Numbering follows ADR-1574 §12. ESC-1..7 are pm-agent's; ARCH-ESC-1..3 were added by the architect.
Where pm-agent and the architect differ, both recommendations are shown; the human decides.

**ESC-1 — Is nesting written into the surface lists, and is the F5 lookalike drop accepted?**

Technical basis (architect's ruling, binding on design): there is one grammar and **no mode
parameter**. Every option below produces the same code; the options differ only in the list text,
so the human can change their mind later with a list edit (subject to the REQ-U2 ordering
constraint). Rev 1's option (B), a `protect`/`exact` mode split, is **withdrawn** (AM-2): an
implicit over-matching mode cannot be used in last-match-wins CODEOWNERS resolution (ADR AF-2), it
cannot make CODEOWNERS equal to the CI gate (AF-3), and its behaviour is invisible in the list.

ESC-1 (i) — option:
- **(A) Lists as written.** Root-anchored, GitHub grammar. CI = overseer = CODEOWNERS exactly (215
  protected / 24 security on today's tree). The overseer **narrows** by 5 protected and 6 security
  tracked files (all `prompts/` mirrors, F3) and by every future nested copy of a P1/P2 pattern. No
  consumer P1/P2 widening.
- **(B′) Nesting written explicitly**, per list and per line, as `**/<p>`. Nothing narrows; the CI
  gate and CODEOWNERS widen to the overseer's set, all three equal by construction. Applied to
  `protected_surfaces.txt`, it widens **every consumer's** CI gate and CODEOWNERS for nested P1/P2
  directories (F9, AM-3) — that additionally needs ARCH-ESC-1.
  - **(B′-security)** — (A) for `protected_surfaces.txt`, (B′) for `security_surfaces.txt` only.
    The security list is not shipped, so this has no consumer effect. The protected list still
    narrows by the 5 `prompts/` mirrors.
- **(C) (A) for the CI gate and CODEOWNERS, keep M3's fallback in the overseer.** Not a unification;
  it leaves the disagreement the issue is about, and it would need a mode, which the architect has
  ruled out. Listed for completeness; not recommended by either party.

ESC-1 (ii) — accept dropping the F5 suffix-lookalike over-matches (`NOTAGENTS.md`, `oauth/x`)? They
were never GitHub semantics and no tracked file is affected. This sub-question gates S3; (i) gates
S5.

Recommendations:
- **Architect: (A)** for both lists, with (B′-security) offered as a free middle path if the human
  wants zero security narrowing. Rationale: the `prompts/` mirrors are "records, not controls", and
  the installer writes controls only at root, so the fallback's protective value is ~0 while its
  consumer cost is real and unmeasured.
- **pm-agent: (B′-security)**, revised from rev 1's (B). Rev 1's goal was zero narrowing; its
  mechanism is withdrawn on the architect's technical ruling, and AF-1 shows that zero narrowing on
  the shipped protected list costs consumers unmeasured gate load. (B′-security) keeps zero
  narrowing where it is free, and limits the human ruling to the 5 protected-list mirrors.
- Both concur on (ii): accept the lookalike drop.

**PM note (dissent on rationale, not on any amendment).** The architect characterises the
`prompts/` mirrors as "records, not controls". That is a product classification, and pm-agent does
not fully agree: prompt artifacts are oversight **evidence** (consumed by prompt-fidelity and the
`ip_check.py` clean-room check), and an unreviewed edit to one could alter the provenance trail for
the governance file it describes. pm-agent does not ask for that to be fixed here: if the human
wants those records gated, the honest way under AD-2 is an explicit `prompts/**` line, which is a
scope change outside this issue (§4). The human should weigh this when ruling on (A) versus
(B′-security) for the protected list.

**ESC-2 — M5 (`scripts/automation/lib/codeowners.py`).** It has no production callers, and its
divergence is pinned by an architect ruling (#559). **Recommended (pm and architect concur):** exempt
it by name from REQ-U8 here, and open a separate issue to retire it (ADR FU-1). The architect notes
that #559's "a shared matcher cannot serve both" premise does not hold for an exact grammar, so the
retirement issue may argue for sharing the module; folding it in here would override #559 and needs
the architect sign-off the pinned test demands.

**ESC-3 — CODEOWNERS fidelity.** **Recommended (concur):** emit no-slash patterns unanchored
(GitHub's any-depth, equal to the CI gate). Emit `**/` lines **only** where the list text itself
contains a `**/` line (ESC-1 (B′)); the generator never invents nested-fallback lines. Under the
single-grammar design there is **no residual**: CODEOWNERS equals the CI gate exactly, so rev 1's
"accept CODEOWNERS ⊆ CI gate" is moot. Under (A), the CODEOWNERS diff is 4 lines (`AGENTS.md`,
`CLAUDE.md`, `METHODOLOGY.md`, `.hos-release` lose their leading `/`).

**ESC-4 — M4, the release-path matcher.** It is a fifth matcher the issue missed. It is
case-insensitive, and its `*` crosses `/` (`release/v*` matches `release/v1/a/b`). **Recommended
(concur, with AM-4):** in scope, under the one grammar. Rewrite the list losslessly:
`**/docs/releases/**`, `**/.hos-release`, `**/.hos-release/**`, `**/changelog*`,
`**/changelog*/**`, `**/release/v*`, `**/release/v*/**` (stored lowercase). Case-insensitivity is
kept by the caller lowercasing the path, not by a matcher option. An M4 error returns "protected"
(new; today an exception propagates). Alternative: leave M4 out and exempt it by name.

**ESC-5 — Missing `protected_surfaces.txt` makes the overseer return "not protected" (F10).**
**Recommended (concur):** change it to protected (fail-closed), matching the CI gate's exit 2. This
only tightens behaviour. The effect reaches `evaluate_reviewer_trigger` (a human reviewer is
requested) and `decide_merge_authority` (HUMAN_REQUIRED), and the CLI's "permissive default" note is
rewritten. Keep the security variant's documented "missing = not relevant", because the protected
list covers its file.

**ESC-6 — Allow-direction no-slash entries (F6).** `SCRIPTS-INDEX.md` and `.hos-manifest` in the
release exclusions would, under the any-depth grammar, exclude nested same-named files from release
review. **Recommended (concur):** anchor them in the list (`/SCRIPTS-INDEX.md`, `/.hos-manifest`).
That keeps one grammar and leaves today's match set identical. (Rev 1's alternative, a mode in which
no-slash means root-only, is withdrawn: the module has no modes, AM-2.) Editing this file triggers
ARCH-ESC-3.

**ESC-7 — Consumer widening (F9).** Nested `AGENTS.md`, `CLAUDE.md`, `METHODOLOGY.md` and
`.hos-release` become protected in consumer repos. **Recommended (concur):** accept, and state it in
the release notes as a behaviour change. Under (A) or (B′-security) this is the whole consumer
change; under (B′) for `protected_surfaces.txt`, ARCH-ESC-1 applies as well.

**ARCH-ESC-1 (architect) — Consumer P1/P2 widening.** Asked only if ESC-1 = (B′) for
`protected_surfaces.txt`: accept that every consumer's required CI check and CODEOWNERS also gate
nested `bin/`, `bootstrap/`, `contract/`, `scripts/framework/`, `scripts/oversight/gates/`,
`.github/workflows/`, `docs/releases/` and similar directories? **Recommended (architect; pm
concurs): do not** — choose (A) for the protected list. Gates S5.

**ARCH-ESC-2 (architect) — Rejected CODEOWNERS lines.** A consumer CODEOWNERS line the grammar
rejects → `check_pr_files` returns HUMAN_REQUIRED (`reason="CODEOWNERS unparseable: <line>"`), and
`resolve_human_reviewer` falls back to the configured human reviewer? GitHub itself skips invalid
lines, but skipping one line in a last-match-wins resolver can mis-attribute ownership. This is a
consumer-visible tightening for any consumer whose CODEOWNERS uses `[`, `!` or `\` (or `?`, if TD-O2
finds it unsupported). **Recommended (architect; pm concurs): yes.** Gates S4.

**ARCH-ESC-3 (architect) — Release-panel verdict invalidation.** ESC-6's edit to
`release_panel_exclusions.txt` changes its sha256, which ADR-1340 AD-3 binds into every
release-panel verdict, so every prior verdict is invalidated even though the excluded set is
identical. **Recommended (architect; pm concurs):** accept, and merge that change only when no
release request is between panel run and authorization. Gates S2.

**Technical-design obligations (not human items; listed for traceability):** TD-O1 (cite GitHub on
whether a literal `/docs` also owns `docs/x`), TD-O2 (cite GitHub on `?`), TD-O3 (enumerate tests
affected by ESC-5 and every `test_codeowners.py` row pinning an F5 over-match).

## 7. Escalation flag (CORE self-flag)

RISK: HIGH. This changes the predicate behind the server-side human-approval gate, the overseer's
protected-surface, security-surface and release routing, CODEOWNERS and reviewer routing. A wrong
translation silently lets governance changes auto-merge. All touched production files are protected
(`scripts/framework/**`, `.github/CODEOWNERS`) or security (`scripts/automation/lib/**`) surfaces.

CONFIDENCE: 85%.
- **High** on F1–F11: code read and match sets measured this session, and independently re-measured
  by the architect (ADR §0).
- **Medium** on the GitHub-oracle edge rows (literal-as-directory, `?`, trailing `/**` on the
  directory itself). Technical design must cite GitHub documentation per oracle row (TD-O1, TD-O2).

BLAST RADIUS:
- every PR's `require-human-approval` result, in HOS and in every consumer;
- the overseer's auto-merge eligibility and human-reviewer routing;
- the release-review file set and the validity of existing release-panel verdicts (ARCH-ESC-3);
- consumer CI breakage if REQ-U5's ship-set rule is missed.

Classification: **structural**. It changes which paths existing controls treat as protected
(widening the CI gate under every option, and narrowing the overseer under ESC-1 (A) or
(B′-security)). It changes CODEOWNERS output, consumer-visible gating (ESC-7, ARCH-ESC-1/2) and
adds fail-closed conditions (ESC-5, ARCH-ESC-2, the AM-7 exit-2 wrapper). None of this may be
applied without human sign-off. This document proposes the changes; it does not authorize them.
Rev 2 itself is a revision of an unapproved proposal and introduces no applied change.

## Human Review Required

- **ESC-1** (i) must be answered before the overseer slice (S5); (ii) before the CI-gate slice (S3).
  pm-agent and the architect **differ** on (i): architect (A), pm-agent (B′-security). Rev 1's mode
  split is withdrawn on the architect's technical ruling.
- **ESC-2** touches an architect ruling (#559).
- **ESC-3..ESC-7** and **ARCH-ESC-1..3** have safe defaults that design may assume. They are not
  binding until the human confirms them. Per the ADR, slices S0 and S1 may proceed before any human
  answer.
- **F3 contradicts the issue's recommendation.** Adopting `scripts/oversight/codeowners.py`
  semantics as-is is protection-narrowing for the overseer, not neutral.
- **F4 is a live fail-open.** The overseer's security check misses repo-root `auth/`, `session/`,
  `crypto/`, `secrets/`, `credentials/`, `authn/` and `authz/`. It is fixed by any option (S5).
- **F10 / AM-7.** The CI gate today exits 1 on an uncaught exception, which reads as "protected, no
  approval" rather than "tooling error".
- The PR is human-gated: protected surfaces and security surfaces, CODEOWNERS.
