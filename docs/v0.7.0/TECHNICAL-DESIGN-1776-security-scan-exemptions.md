# TECHNICAL DESIGN — #1776: `security_scan` dependency-advisory exemptions (black, PyJWT) and the PyJWT floor

**Issue:** #1776 (`bug`, `process-gap`, `priority:critical`, milestone v0.7.0 — Quality)
**Branch:** `worker-1776-security-scan-exemptions-v2-261006053501-3656609`
**Status:** **ARCHITECT-APPROVED (iteration 2, 2026-10-06), with corrections A1–A5 applied
in this doc by the architect (§14), and implementation-time rulings B1–B2 applied (§15):
record 3 (PyJWT PYSEC-2026-4146) is DROPPED, so the roster is two black records; a malformed
`fix_versions` makes the advisory malformed.** The coder implements this document as amended.
H2/H3 still need explicit human confirmation at PR review; this does not block coding.
**Change classification:** `structural` for the suppression policy (what a *blocking security
gate* stops blocking on) — **pre-authorized** by the human rulings on #1776 of 2026-10-02
(time-boxed, individually-justified, visible exemptions; #1754 shape; anything new fails
closed) and 2026-10-03 (ScottThurlow: "Human authorizing timebox approach" for black; PyJWT
handled by floor + one exemption). `additive` for the floor, the logic module, the
protected-surface glob and the tests.

## HOS self-flag

```
RISK: MEDIUM
CONFIDENCE: HIGH on scope, roster, keying, fail-closed matrix and tests — every advisory id,
            fix version and dependency constraint below was probed live on 2026-10-06
            (pip-audit, PyPI metadata, a pip --dry-run resolve), not recalled.
            MEDIUM on the H2 source-repo predicate (§5): it is a new positive check, chosen
            from what hos_install.sh demonstrably does and does not copy to consumers.
BLAST RADIUS: scripts/oversight/gates/security_scan.sh (PROTECTED), new
            scripts/oversight/security_scan_logic.py, scripts/oversight/requirements.txt
            (ships to every consumer on upgrade), scripts/framework/protected_surfaces.txt +
            generated .github/CODEOWNERS + docs/AGENT-IDENTITY.md §9.0 (all PROTECTED), and a
            one-row amendment to ADR-1935 §3.5/§4. Two exact entries (the new module and
            secret_scan_logic.py) become human-gated — not a glob (architect iteration-2 A1).
            The shared oversight venv changes on reconcile: PyJWT 2.13.0 -> 2.15.x and
            semgrep 1.178.0 -> 1.179.0 (forced by semgrep's own pyjwt pin, §0 VF-3).
```

### Human Review Required

- Protected surfaces touched (`scripts/oversight/gates/**`, `scripts/framework/**`,
  `docs/AGENT-IDENTITY.md`, `.github/CODEOWNERS`). The PR **must** carry a human approval; no
  bot approval counts.
- **H2 (consumer scope) — default applied, needs human confirmation at PR review.** The roster
  is active **only** in the HOS source repository, by a positive check; any ambiguity means an
  empty roster, i.e. today's behaviour. Consequence the human should see: an installed
  consumer's `security_scan` stays red on `black` (consumers inherit the same `<25` pin) until a
  consumer-owned roster exists — that is out of scope here (§10).
- **Deviation from the 2026-10-03 wording (§15 B1) — tell the human at PR review.** The ruling
  said "PyJWT by floor + one exemption". The exemption is not shipped. The floor alone clears
  all 13 PyJWT advisories, because PYSEC-2026-4146 affects only 2.11.0–2.13.0. This is
  strictly narrower than what was authorized, so no pre-clearance is needed, but the PR body
  must say so.
- **H3 (expiry) — default applied, needs human confirmation at PR review.** Both records
  expire **2027-01-31**; `EXPIRING SOON` from 2027-01-17; a test (TC-X5) turns the repo's
  required `tests` check red from **2027-02-01** if nobody has renewed or removed them. That
  cliff is deliberate — it is the forcing function — but it is a scheduled repo-wide red.
  **Architect note:** the black records' only exit is #1961, which is today `priority:low` in
  milestone v0.7.12. As scheduled, the cliff is likely to fire for black. The human should either
  pull #1961 forward so that it lands before 2027-01-17, or accept now that black will need a
  renewal decision in January.
- **Protected-list change (architect A1).** This PR newly human-gates
  `scripts/oversight/secret_scan_logic.py` and the new module. That is a small, deliberate
  increase in human-approval load, ahead of ADR-1935's ESC-1. It is
  covered by ADR-1935's own classification (both P3, "which findings are suppressed"), and it
  keeps the suppression decision from moving out of the protected `gates/**` into an
  unprotected file.
- **New since iteration 1:** the PyJWT floor forces a `semgrep` minor bump (1.178.0 → 1.179.0)
  in every venv that reconciles, because semgrep 1.178.0 pins `pyjwt~=2.13.0` (§0 VF-3). The
  only metadata difference between the two semgrep releases is that pin.

---

## 1. Changelog vs iteration 1

| # | Iteration 1 | Iteration 2 | Driver |
|---|---|---|---|
| 1 | 10 records across anyio/black/click/mcp/pip | **3 records**: black ×2, pyjwt ×1 (**→ 2 black records, §15 B1**) | 2026-10-03: anyio/click/mcp/pip resolved by ordinary bumps |
| 2 | `cryptography>=50.0.0` floor (R1), TC-S7 forbids exempting it | **Dropped entirely.** No cryptography floor, no cryptography test. H1 is moot | 2026-10-03: cryptography out of scope (venv already on 50.0.2) |
| 3 | `ensure_venv.sh` requirements-fingerprint reconcile (§7) | **Dropped.** Stale venvs reconcile with one documented command; the gate names it (§6.5). `ensure_venv.sh` is not touched | Architect blocking item 2 had six unresolved sub-points for machinery whose only remaining job is one floor; the gate already fails closed and truthfully on a stale venv |
| 4 | — | **`pyjwt>=2.15.0` floor** (clears 12 of 13 PyJWT advisories) + one no-fix exemption (PYSEC-2026-4146), with a precisely defined no-fix key (§4.2). **Superseded by §15 B1:** the floor clears all 13; the exemption is dropped; the no-fix key stays as a tested, unused mechanism | 2026-10-03 consolidation ruling |
| 5 | Roster shipped to consumers (unaddressed) | **Roster active only in the HOS source repo** via a positive check; mode printed every run (§5) | Architect blocking item 1; H2 default |
| 6 | Protected surface: the one new module | **Two exact entries**, `scripts/oversight/security_scan_logic.py` and `scripts/oversight/secret_scan_logic.py` (closes the secret-scan hole now); `docs/AGENT-IDENTITY.md` §9.0 kept in sync; ADR-1935 §3.5/§4 amended with the new file. *(Iteration 2 originally proposed the glob `scripts/oversight/*_logic.py`; the architect replaced it — ADR-1935, accepted 2026-10-05, lists `scripts/oversight/` per file and rules `prompt_audit_logic.py`/`retry_rescue_logic.py` UNPROTECTED, so the glob would contradict a binding ruling. See §14 A1.)* | Architect blocking item 3; ADR-1935 |
| 7 | Bandit fail-open left in place | **Bandit `|| echo "0"` fixed**; empty `dependencies` → exit 2; *any* non-mapping entry (incl. falsy) kept; `skip_reason` deps printed `NOT CHECKED`; closing `GATE PASS` line names NOT CHECKED/SKIP | Architect blocking item 4 |
| 8 | Expiry 2026-12-22 | **2027-01-31**, 14-day warning, dated test cliff | Architect blocking item 5; H3 default |
| 9 | TC-G1 live pip-audit run inside pytest; TC-E2 installed-version check | **Both removed from the suite** and moved to landing evidence (§8.2). A test that queries a live advisory database would re-create the always-red disease inside the required `tests` check the first day any venv package gets a new advisory | Self-review of iteration 1 |
| 10 | TC-G4 used invalid JSON to reach exit 2 | Uses **valid JSON of the wrong shape**. Invalid JSON never reaches the module — `_run_pip_audit`'s success predicate (#672) rejects it and the run ends in the `NOT CHECKED` path | Correctness of iteration 1's test |
| 11 | 8 components, ~5 slices, 3 follow-ups | **11 files** (F11 added by architect A1), 3 slices, 1 required follow-up issue | "≤15 files" constraint |

**Settled in iteration 1 and carried unchanged:** keying on canonical name + advisory id +
version bound + expiry; `fix_versions`/`aliases` never part of the bound for fixed advisories;
expiry as a `datetime.date` literal; **no `--today` flag and no environment override for the
clock** (tests pass an explicit date to the pure function); pure `*_logic.py` module with a CLI
shim mirroring `secret_scan_logic.py`; exit 0/1/2; dedup on `(name, version, id)`; full roster
printed every run; `HOS_PIP_AUDIT_BIN` binary seam only (never a payload override); pip-audit
non-completion stays fail-open but is renamed `NOT CHECKED`; no CI wiring now.

---

## 0. Verification findings (2026-10-06, live)

**VF-1 — live audit.** `scripts/oversight/.venv/bin/pip-audit --format json --desc on`, rc 1,
116 dependencies, no `skip_reason` entries:

| package | installed | advisory | fix_versions | aliases |
|---|---|---|---|---|
| black | 24.10.0 | PYSEC-2026-2121 (**reported twice**) | 26.3.1 | CVE-2026-32274, GHSA-3936-cmfr-pm3m |
| black | 24.10.0 | PYSEC-2026-2120 | 26.3.0 | CVE-2026-31900, GHSA-v53h-f6m7-xcgm |
| pyjwt | 2.13.0 | PYSEC-2026-4140, -4142..-4145, -4147..-4152 | 2.14.0 | — |
| pyjwt | 2.13.0 | PYSEC-2026-4141 | 2.15.0 | GHSA-42vr-xj54-vc7v |
| pyjwt | 2.13.0 | CVE-2026-102275 | 2.15.0 | GHSA-x33g-cr3x-6449 |
| pyjwt | 2.13.0 | **PYSEC-2026-4146** | **`[]` (no fix)** | CVE-2026-103001, GHSA-gvp8-978c-rx2q |

Note the pyjwt advisory id `CVE-2026-102275` is a CVE, not a PYSEC id — the key is whatever
`id` pip-audit reports, never assumed to be PYSEC-shaped.

**VF-1 correction (§15 B1, architect re-verified 2026-10-06).** The `[]` for PYSEC-2026-4146
does **not** mean "no fix exists". Both OSV records (PYSEC-2026-4146 and alias
GHSA-gvp8-978c-rx2q) give the range `introduced 2.11.0, last_affected 2.13.0`. That is a
`last_affected` bound, not a `fixed` event, so pip-audit has no fix version to print. PyJWT
2.15.x is outside the range. A live pip-audit on the reconciled venv (PyJWT 2.15.1, semgrep
1.179.0) reports **only** black: PYSEC-2026-2121 ×2 and PYSEC-2026-2120.

**VF-2 — reachability.** `grep -rn "import jwt\|from jwt\|import black\|from black"` over
`scripts/ bootstrap/ bin/ tests/` (excluding `.venv`) → no hits. `bootstrap/get_app_token.sh`
signs the App JWT with `openssl` (line 114). In the venv, PyJWT is `Required-by: mcp, semgrep`;
semgrep imports `jwt` only under `semgrep/mcp/` (its MCP server). HOS invokes semgrep only as a
scanner against a vendored ruleset (`validators/static_analysis_js.py`), never `semgrep mcp`.
`black` runs only as `black --check --diff --quiet <files>` (`gates/lint_check.sh:124`), with
`[tool.black]` in `pyproject.toml` setting only `line-length` and `target-version` — no
`--python-cell-magics` anywhere. No workflow uses the `psf/black` GitHub Action.

**VF-3 — the floor forces a semgrep bump.** semgrep 1.178.0 (installed) declares
`pyjwt[crypto]~=2.13.0`; semgrep 1.179.0 (PyPI, 2026-10-02) declares `pyjwt[crypto]>=2.15.0,<3`
— the **only** `requires_dist` difference between the two. mcp 1.29.0 declares
`pyjwt[crypto]>=2.10.1`. A `pip install --dry-run -r <requirements.txt + pyjwt>=2.15.0 +
packaging>=23.0>` against this venv (no `--upgrade`) resolves to exactly two changes:
**semgrep 1.179.0, PyJWT 2.15.1**. Nothing else moves; black stays 24.10.0.

**VF-4 — `ensure_venv.sh` reads requirements only at create time** (unchanged from iteration 1
TD-VF-4). A new floor therefore reaches an existing venv only by an explicit install; CI builds
a fresh venv per job and gets it automatically.

**VF-5 — what consumers receive.** `hos_install.sh` syncs `scripts/oversight/` whole (so the
module and `requirements.txt` ship). Of `bootstrap/` it copies only `get_app_token.sh`,
`hos_repo_sync.sh`, `sync_apps_env.sh`, `validate_setup.sh`, `apps.env.template`, `worker`,
`overseer` — **never `bootstrap/hos_install.sh`** — and stamps `.hos-release` at the target
root. `scripts/automation/lib/dimension_registry.py` already uses `.hos-release` as the
"installed tree" marker. These two facts are the basis of §5.

**VF-6 — `*_logic.py` population.** 11 existing modules match `scripts/oversight/*_logic.py`
(agents_static, changeset, panel, prompt_audit, release_artifact, release, release_panel,
retry_rescue, second_review, secret_scan, validation). **ADR-1935 §3.5 (accepted 2026-10-05)
classifies these per file: nine are P, `prompt_audit_logic.py` and `retry_rescue_logic.py` are
U (N3).** A glob would therefore contradict it, so this PR adds only the two exact paths
(architect A1). `protected_surfaces.txt`'s header requires `docs/AGENT-IDENTITY.md` §9.0 and
CODEOWNERS to stay in sync with it.

---

## 2. File list (the whole PR)

| # | Path | Change | Protected |
|---|---|---|---|
| F1 | `docs/v0.7.0/TECHNICAL-DESIGN-1776-security-scan-exemptions.md` | this doc | no |
| F2 | `scripts/oversight/security_scan_logic.py` | **new** | yes (via F5) |
| F3 | `scripts/oversight/gates/security_scan.sh` | pip-audit branch → module; bandit fail-open fix; summary text | **yes** |
| F4 | `scripts/oversight/requirements.txt` | `pyjwt>=2.15.0`, `packaging>=23.0` | no |
| F5 | `scripts/framework/protected_surfaces.txt` | add two exact lines after `scripts/oversight/validators/schema.py`: `scripts/oversight/secret_scan_logic.py`, `scripts/oversight/security_scan_logic.py` (one-line comment: finding/advisory-level suppression for blocking gates, #1776, ADR-1935 P3) | **yes** |
| F6 | `.github/CODEOWNERS` | regenerated (`scripts/framework/regen_all.sh`) | **yes** |
| F7 | `docs/AGENT-IDENTITY.md` | §9.0 code block: add the same two paths | **yes** |
| F8 | `SCRIPTS-INDEX.md` | regenerated (`regen_all.sh`) for F2 | no |
| F9 | `tests/oversight/test_security_scan_exemptions.py` | **new** | no |
| F10 | `DECISIONS.md` | append-only entry | no |
| F11 | `docs/v0.7.0/ADR-1935-protected-surface-recalibration.md` | architect amendment (§14 A1): §3.5 table row `security_scan_logic.py \| P \| P3 \| Advisory-level suppression for security_scan.sh (#1776).` and the line `scripts/oversight/security_scan_logic.py` in the §4 list, after `secret_scan_logic.py`. Nothing else in ADR-1935 changes | no |

Pipeline artifacts (sign-off register, validator summary) are additional but stay within 15.
**Not touched:** `ensure_venv.sh`, `run_gates.sh`, `lib/changeset.sh`, any workflow.

---

## 3. Decisions

**TD-D1 — roster is an in-module tuple** `SUPPRESSIONS: tuple[Exemption, ...]` (unchanged; #1754
shape; no data file, no loader).

**TD-D2 — keying (fixed advisories).** An `Exemption` with `fixed_in` set matches a reported
advisory iff all hold: (1) `canonicalize_name(reported name) == record.package` (PEP 503);
(2) `reported id == record.advisory_id` (exact string); (3)
`Version(installed) < Version(record.fixed_in)` (PEP 440); (4) `today <= record.expires`.

**TD-D2b — keying (no-fix advisories).** *(§15 B1: no shipped record uses this key. It stays
in the module as a reviewed, fail-closed mechanism and is tested through an injected rule. Any
future record that uses it is a protected-surface change and needs a human ruling.)* An
`Exemption` with
`fixed_in=None` replaces condition (3) with: **(3′) the deduplicated advisory's `fix_versions`
is empty** — no source pip-audit consulted reports any fix. Conditions 1, 2, 4 are unchanged, and
the installed version must still parse as PEP 440 (else `UNPARSEABLE VERSION`). Rationale:
- The record becomes inert at the exact moment the premise ("no fix exists") stops being true;
  pip-audit then reports a fix, the advisory is **kept**, and the note says
  `FIX NOW AVAILABLE` with the remedy (raise the floor, delete the record).
- Dedup unions `fix_versions` across duplicate records (§4.3), so if *any* source reports a fix
  the exemption stops applying — disagreement between sources resolves fail-closed. This is why
  emptiness is safe to key on even though TD-D3 forbids keying on fix-version *strings*.
- No upper version bound is added: the justification is non-reachability (HOS never calls
  `jwt.decode`), which does not vary with the PyJWT version, and a bound would re-red the gate
  on the next PyJWT patch release that still lacks the fix. Expiry is the time box.

**TD-D3 — `fix_versions`/`aliases` are display-only** for fixed advisories (the same advisory
arrives with `26.2` vs `26.2.0` from different sources). Emptiness test in TD-D2b is the only
use, and it is fail-closed.

**TD-D4 — expiry** is a `datetime.date` literal; `today` is a parameter of the pure functions;
the CLI shim reads `datetime.datetime.now(datetime.timezone.utc).date()` exactly once. **No
`--today` flag, no environment override.**

**TD-D5 — expiry behaviour.** Valid through `expires` inclusive; kept with `EXEMPTION EXPIRED`
from the next day. `EXPIRING SOON` printed for every active record with
`0 <= (expires - today).days <= 14`.

**TD-D6 — every failure to decide is exit 2**, never a pass (matrix §4.5). Exit 1 means exactly
"at least one advisory is kept".

**TD-D7 — no venv-reconcile machinery.** A venv built before the floor is genuinely vulnerable
(PyJWT 2.13.0); the gate failing on it is correct. The kept-advisory block always ends with a
`HINT` naming the one-command remedy (§6.5). CI and every freshly built venv get the floor
automatically (VF-4). The worker clone is reconciled as a landing step (§8.2); other long-lived
clones (Human, Overseer) reconcile once when the gate tells them to. Chosen over iteration 1's
fingerprint reconcile because it adds no code to a file ~100 call sites source, needs no locking
or failure-isolation design, and cannot float unpinned packages.

**TD-D8 — pip-audit non-completion stays fail-open**, worded `NOT CHECKED`, and the closing
`GATE PASS` line says so (§6.4). Making it blocking needs its own ruling (offline local runs).

**TD-D9 — protected surface: two exact entries** (`security_scan_logic.py`,
`secret_scan_logic.py`), consistent with ADR-1935's per-file rule for `scripts/oversight/`
(architect iteration-2 ruling A1, superseding the iteration-1 glob ruling).

**TD-D10 — exemptions are environment-scoped.** pip-audit audits the installed venv, not the
diff; a PR that newly adds a direct `black` dependency would inherit the exemption for those
two advisory ids only (§15 B1). Every other package and every other advisory id, including
every PyJWT id, fails closed. The roster is printed every run, so the two are never invisible.

**TD-D11 — roster scope = HOS source repo only** (§5, H2 default).

---

## 4. F2 — `scripts/oversight/security_scan_logic.py` (contract)

### 4.1 File rules
- Module docstring at `secret_scan_logic.py`'s density: the problem (#1776), the rulings
  (2026-10-02, 2026-10-03), why advisory-level rather than a pip-audit skip, the no-fix key,
  the H2 scope rule, visibility, purity. Every roster record carries a comment explaining itself.
- `from __future__ import annotations`; stdlib `argparse, datetime, json, os, sys,
  pathlib, typing`; `packaging.version.Version`, `InvalidVersion`, `packaging.utils.canonicalize_name`.
- `packaging` import is guarded: on `ImportError` the module records the error and `main`
  returns 2 with a stderr message (so a missing dependency can never surface as exit 1).
- Pure: every function except `roster_mode` (filesystem `lexists`/`isfile` only) and `main`
  performs no I/O and reads no clock. No `except Exception: pass`.

### 4.2 Types (NamedTuple)
```
Advisory:  package: str; key: str (canonical); version: str; advisory_id: str;
           fix_versions: tuple[str, ...]; aliases: tuple[str, ...];
           malformed: bool; malformed_why: str | None
Exemption: package: str (PEP 503 canonical); advisory_id: str;
           fixed_in: str | None (None = no fix published, TD-D2b);
           expires: datetime.date; reason: str (>= 40 chars); tracking_issue: int
Skipped:   name: str; version: str; reason: str        # pip-audit skip_reason entries
AuditDoc:  advisories: list[Advisory]; skipped: list[Skipped];
           raw_count: int; distinct_count: int; dependency_count: int
RosterMode: active: bool; why: str
Kept:      advisory: Advisory; note: str | None
Suppressed: advisory: Advisory; exemption: Exemption
Decision:  kept: list[Kept]; suppressed: list[Suppressed];
           roster: list[tuple[Exemption, str]]   # (record, status)
```

### 4.3 Functions

`parse_audit(document: object) -> AuditDoc` — raises `AuditParseError` when nothing can be
audited: root not a mapping; `dependencies` missing or not a list; **`dependencies` an empty
list** (a venv always contains at least pip-audit and its deps, so zero means nothing was
audited). Per entry:
- **any** non-mapping dependency entry (including `None`, `0`, `""`, `[]`) → one
  `Advisory(malformed=True, advisory_id="<unattributable>")`;
- mapping with `skip_reason` (string) → `Skipped`; **if the same entry also carries a non-empty
  `vulns`, those vulns are processed exactly as for an ordinary entry** (a skip marker never
  hides a reported advisory — architect A3);
- mapping with `vulns` absent or `[]` → ignored;
- `vulns` present but not a list → one malformed advisory;
- `name`/`version` missing or non-string while `vulns` non-empty → each vuln malformed;
- a vuln entry not a mapping, or `id` missing/non-string/empty → malformed, `advisory_id="<unknown>"`;
- **`fix_versions` (decision-bearing, §15 B2):** absent, or present but not a `list` whose
  every element is a `str` → the vuln is **malformed**:
  `Advisory(malformed=True, advisory_id=<the vuln's id>, malformed_why="'fix_versions' is missing")`
  or `"'fix_versions' is {type(value).__name__}, not a list of strings"`. `[]` stays valid
  and means "no fix reported". The id check runs first, so a vuln with no usable id is still
  `<unknown>`.
- **`aliases` (display-only):** absent or not a list of strings → coerced to `()`. It never
  enters a decision, so leniency here cannot open anything.

Dedup: collapse non-malformed advisories on `(key, version, advisory_id)`, first occurrence
wins, `fix_versions` and `aliases` **unioned** (order-preserving). Malformed advisories never
dedup. `raw_count` = advisories before dedup, `distinct_count` = after,
`dependency_count` = `len(dependencies)`.

`validate_exemptions(rules) -> list[str]` — errors, empty = valid. Per record: `package`
non-empty and `canonicalize_name(p) == p`; `advisory_id` non-empty, no whitespace; `fixed_in`
is `None` or parses as `Version`; `expires` is a `date` and **not** a `datetime`; `reason`
`len(reason.strip()) >= 40`; `tracking_issue` an `int` (not `bool`) `> 0`. Across records:
`(package, advisory_id)` unique.

`roster_mode(root: Path) -> RosterMode` — §5.

`partition(advisories, rules, today) -> Decision` — per advisory, first matching row wins:

| order | situation | result | note |
|---|---|---|---|
| 1 | `malformed` | Kept | `UNATTRIBUTABLE: {malformed_why} — a malformed audit record is never exempted.` |
| 2 | no rule with same `(key, advisory_id)` | Kept | `None` |
| 3 | installed version not PEP 440 | Kept | `UNPARSEABLE VERSION: installed version {v!r} is not PEP 440, so it cannot be bounded by the exemption.` |
| 4 | `fixed_in` set and `Version(v) >= Version(fixed_in)` | Kept | `PREMISE BROKEN: the exemption declares fixed_in={f}, but pip-audit reports this advisory at installed {v} (>= {f}). Re-check the advisory and update or remove the record (#{issue}).` |
| 5 | `fixed_in is None` and `fix_versions` non-empty | Kept | `FIX NOW AVAILABLE: the exemption was granted because no fix existed, but pip-audit now reports fix {', '.join(fix_versions)}. Raise the floor in scripts/oversight/requirements.txt and remove the record (#{issue}).` |
| 6 | `today > expires` | Kept | `EXEMPTION EXPIRED {expires} (today {today}) — #{issue}. It no longer applies; renew only with a fresh human decision, or fix the dependency. Original justification: {reason}` |
| 7 | otherwise | Suppressed | — |

Roster status per rule: `APPLIED` if it suppressed ≥1 advisory; `NOT APPLIED: <KEYWORD>` if an
advisory matched `(key, id)` but was kept by rows 3–6 (`KEYWORD` ∈ `UNPARSEABLE VERSION`,
`PREMISE BROKEN`, `FIX NOW AVAILABLE`, `EXEMPTION EXPIRED`); else
`NOT NEEDED (not reported in this environment)`.

`render(doc, decision, mode, rules, today) -> tuple[list[str], int]` — pure; exact output §6;
status 1 iff `decision.kept` non-empty, else 0.

`run_filter(stdin_text, rules, mode, today) -> tuple[list[str], list[str], int]` — (stdout lines,
stderr lines, status). `json.loads` → `parse_audit` → (if `mode.active`) `validate_exemptions`
→ `partition` → `render`. JSON errors, `AuditParseError`, and validation errors → stderr lines,
status 2. This is the seam tests use to inject a broken roster through the CLI path (TC-F3/F6).

`main(argv=None) -> int` — argparse, one required subcommand `filter`. Reads stdin, computes
`mode = roster_mode(Path(__file__).resolve().parents[2])`, `rules = SUPPRESSIONS if mode.active
else ()`, `today` from the UTC clock, calls `run_filter`, prints, returns status. The
`__main__` guard converts any uncaught exception into stderr
`GATE FAIL: security_scan_logic crashed ({Type}: {msg}) — nothing was decided` and exit 2.

### 4.4 Roster (`SUPPRESSIONS`) — exact entries

**§15 B1: the shipped roster is records 1 and 2 only. Record 3 below is DROPPED.** It is kept
in this table, struck, as the record of what was ruled out and why. Do not implement it.

Both: `expires=datetime.date(2027, 1, 31)`. `reason` text must be full prose answering
*what is the vulnerability, how does the package get here, why is it unreachable in HOS* — the
text below is the minimum content, the coder may tighten wording but not drop a clause.

| # | package | advisory_id | fixed_in | tracking_issue | reason (minimum content) |
|---|---|---|---|---|---|
| 1 | `black` | `PYSEC-2026-2120` | `"26.3.0"` | `1961` | Black's **GitHub Action** with `use_pyproject: true` reads the Black version from `pyproject.toml`, so a malicious PR could point it at a malicious package and execute code in the Action. HOS never uses the Black GitHub Action (no workflow references `psf/black`); black runs only as a local formatter checker (`lint_check.sh`: `black --check --diff --quiet <files>`). The fix (26.3.0) is blocked by the deliberate `black>=24.0,<25.0` pin (#103); the upgrade plus the 117-file reformat is #1961. Human ruling #1776, 2026-10-03. |
| 2 | `black` | `PYSEC-2026-2121` | `"26.3.1"` | `1961` | Black builds its cache-file name from formatting options and placed the `--python-cell-magics` value in it unsanitised, letting whoever controls that option write cache files to arbitrary paths. HOS never passes `--python-cell-magics`: `lint_check.sh` invokes `black --check --diff --quiet <files>` and `pyproject.toml [tool.black]` sets only `line-length` and `target-version`. Fix (26.3.1) blocked by the #103 pin; tracked in #1961. Human ruling #1776, 2026-10-03. |
| ~~3~~ | ~~`pyjwt`~~ | ~~`PYSEC-2026-4146`~~ | ~~`None`~~ | ~~#1997~~ | **DROPPED (§15 B1): affected range is 2.11.0–2.13.0, so at the floor it is not reported, and below the floor 12 other PyJWT advisories fail the gate regardless. The record could never be what makes the gate pass.** Original text: `jwt.decode()`/`decode_complete()` mutate a caller-supplied `options` dict when `verify_signature` is falsy, so a reused dict can silently disable claim checks on a later verifying call. **No fixed release exists** (pip-audit reports no fix as of 2026-10-06; latest PyJWT 2.15.1). HOS code never imports `jwt` and signs the App-token JWT with openssl (`bootstrap/get_app_token.sh`); PyJWT is present only as a dependency of semgrep and of mcp (which is itself present only because semgrep requires it), and both are exercised only by semgrep's MCP server (`semgrep mcp`), which HOS never runs. The other 12 PyJWT advisories are cleared by the `pyjwt>=2.15.0` floor, not exempted. Human ruling #1776, 2026-10-03. |

~~`tracking_issue` for record 3 is the number of the follow-up issue opened before the PR
(§9); it must not be `1776` (that issue closes on merge).~~ (§15 B1: #1997 is closed as
not-needed. No shipped record may use `tracking_issue=1776`; R4 pins that rule.)

**Coder obligation:** re-run pip-audit and confirm each `advisory_id` and `fixed_in` against
the tool output and advisory text before writing the records. If one has disappeared or
changed id, do not invent a record — omit it and say so in the PR body. PYSEC-2026-2121 is
reported twice today; that is a dedup case, not two records.

### 4.5 Fail-closed matrix

| condition | exit |
|---|---|
| stdin not JSON; root not a mapping; `dependencies` missing / not a list / empty | **2** |
| active roster fails `validate_exemptions` (even if the audit is clean) | **2** |
| `packaging` not importable; any uncaught exception | **2** |
| malformed dependency/vuln entry (incl. missing or non-list-of-strings `fix_versions`, §15 B2; and, §16, a non-`skip_reason` entry lacking a non-empty-str `name`/`version` or a list `vulns`); unparseable version; premise broken; fix now available; expired; advisory not on roster | 1 |
| `skip_reason` dependencies present, nothing kept | 0 (each printed `NOT CHECKED`) |
| any completed attempt (rc 0/1) unparseable and no attempt readable → GATE FAIL (§16 rounds 2-3) | gate exit 1 (`GATE FAIL`, never NOT CHECKED) |
| pip-audit timeout / network failure (rc not in {0,1}) after retries | 0 (`NOT CHECKED`, TD-D8) |
| everything suppressed, or no advisories | 0 (mode + roster always printed) |

---

## 5. Roster scope — the H2 positive check (`roster_mode`)

`root` = the repository containing the module (`Path(__file__).resolve().parents[2]`), not the
cwd. Evaluate in order; first hit wins:

1. any `OSError` while probing → `RosterMode(False, "could not determine: {Type}: {msg}")`;
2. `os.path.lexists(root / ".hos-release")` → `RosterMode(False, "installed tree: .hos-release present")`;
3. not `(root / "bootstrap" / "hos_install.sh").is_file()` → `RosterMode(False, "bootstrap/hos_install.sh not found")`;
4. else → `RosterMode(True, "HOS source repository: bootstrap/hos_install.sh present, no .hos-release")`.

Inactive ⇒ `rules = ()` ⇒ every advisory enforced, exactly today's behaviour. The shipped
`SUPPRESSIONS` is not validated in inactive mode (a defect in HOS's roster must not break a
consumer's gate; the HOS test suite validates it). **Boundary:** a consumer could activate the
roster only by deleting its own `.hos-release` *and* adding `bootstrap/hos_install.sh` — a
deliberate act in its own repo, which also breaks its installer state; accepted and named.
**Known fail-closed edge:** if HOS ever self-installs (dogfooding writes `.hos-release` into the
source repo), the roster turns INACTIVE and the gate goes red on the two black advisories. That is
the safe direction and the mode line names the cause. Whoever lands self-install must revisit
this predicate.

---

## 6. Gate output format (exact)

Lines from the module, in this order, **always** (including passing runs). `{}` are fields;
everything else is literal. Tests assert substrings, not column alignment.

1. **Mode line** — one of:
   - `  Exemption roster: ACTIVE ({why}) — {n} record(s), #1776`
   - `  Exemption roster: INACTIVE ({why}) — every advisory is enforced; a consumer-owned roster is not yet supported (#1776 H2)`
2. **Roster** (active only), one line per record in `SUPPRESSIONS` order:
   `    {package} [{advisory_id}] fixed_in {fixed_in or "none published"} — expires {YYYY-MM-DD} — {status} — #{tracking_issue}`
3. **Expiry warnings** (active only), per qualifying record:
   `  EXPIRING SOON: {package} [{advisory_id}] exemption expires {date} ({d} day(s)) — renew only with a fresh human decision, or fix the dependency (#{issue})`
4. **Not-audited dependencies**, per `Skipped`:
   `  NOT CHECKED: {name} {version} was not audited by pip-audit ({reason})`
5. **Suppressions**, if any:
   `  {k} advisory(ies) suppressed by a time-boxed exemption:` then per item
   `    {package} {version} [{advisory_id}] fix: {fix_versions or "none"} — exempt until {date} (#{issue}): {reason}`
6. **Kept**, if any:
   `GATE FAIL: {k} dependency advisory(ies) not covered by an exemption:` then per item
   `  {package} {version} [{advisory_id}] fix: {fix_versions or "none"}` and, when a note exists,
   `    {note}`; then exactly one line:
   `  HINT: if scripts/oversight/requirements.txt declares a floor above an installed version listed here, this venv predates it — run: scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt (no --upgrade). Otherwise the advisory is new: upgrade the package, or get a human ruling before adding an exemption.`
7. **Pass summary**, if nothing kept:
   `OK: no dependency advisories outside the exemption roster ({s} suppressed; {distinct} distinct advisory(ies) from {raw} raw record(s); {deps} dependencies read{", " + str(n) + " NOT CHECKED" if n else ""})`

Exit-2 errors go to **stderr**, e.g. `GATE FAIL: could not parse pip-audit output ({Type}: {msg}) — refusing to report a pass on an audit that cannot be read`,
`GATE FAIL: exemption roster invalid — {error}` (one line per error).

### 6.1 Expected output in this repo after landing (AC-1)
*(Corrected by §15 B1.)* Mode ACTIVE, `— 2 record(s), #1776`. The roster shows both black
records `APPLIED`. The suppressions block lists 2 advisories.
`OK: … (2 suppressed; 2 distinct advisory(ies) from 3 raw record(s); N dependencies read)`.
No pyjwt line appears anywhere.

---

## 7. F3 — `scripts/oversight/gates/security_scan.sh`

Changeset parsing, `INV-SELECTOR` case, suspension check and argument grammar are untouched.

**7.1 Bandit (fail-open fix only; stays inline).** Replace the `HIGH_COUNT=$(… || echo "0")`
assignment with a form that cannot abort under `set -e` and cannot default to zero:
`if HIGH_COUNT=$(…python snippet…) && [[ "$HIGH_COUNT" =~ ^[0-9]+$ ]]; then <existing logic> else echo "GATE FAIL: bandit output could not be parsed — nothing was decided; this is a failure to check, not a clean result"; ERRORS=$((ERRORS + 1)); fi`.
Keep `2>/dev/null` off the count snippet so the parse error is visible. The finding-printer
snippet's `|| true` may stay (display only, after the count already decided).

**7.2 pip-audit.**
1. Declare `AUDIT_STATE="not-run"` and `AUDIT_STATUS=0` before the branch.
2. Resolution: `PIP_AUDIT="${HOS_PIP_AUDIT_BIN:-$VENV_BIN/pip-audit}"`, with a comment
   mirroring `secret_scan.sh:130` (binary seam, off by default, inert in the real pipeline; there
   is no payload override). If not executable → existing `SKIP:` text, `AUDIT_STATE="skipped"`.
3. `_run_pip_audit` and its rc-0/1-plus-parseable-JSON predicate (#672): unchanged except using
   `$PIP_AUDIT`.
4. Retry exhaustion → print
   `NOT CHECKED: pip-audit did not complete after retries — the dependency audit was NOT performed. This is a failure to check, not a clean result.`;
   `AUDIT_STATE="not-checked"`; `ERRORS` unchanged (TD-D8). Exception (§16 rounds 2-3): if any
   attempt COMPLETED (rc 0/1) but its output was not valid JSON (`_PIP_AUDIT_UNPARSEABLE=1`), print
   `GATE FAIL: pip-audit completed at least once but its output could not be parsed, and no attempt produced a readable scan (<n> attempt(s)) — a scan whose result cannot be read is never treated as a pass.`,
   `AUDIT_STATE="unparseable"`, `ERRORS += 1` (a corrupt result is never a pass).
5. Success → `PYTHONSAFEPATH=1 "$OVERSIGHT_PYTHON" "$GATES_DIR/../security_scan_logic.py" filter < "$PIP_AUDIT_TMP" || AUDIT_STATUS=$?`
   (the venv interpreter set by `ensure_venv.sh:24`, as every other snippet in this file uses —
   no `python3` fallback, which would lack `packaging` and turn a healthy run into exit 2);
   `AUDIT_STATE="checked"`; `AUDIT_STATUS != 0` → `ERRORS++`.
6. **Delete** the `VULN_COUNT` snippet and the finding-printer snippet (and their
   `|| echo "0"` / `|| true`). No JSON is parsed in the shell's pip-audit path except #672's
   predicate.

**7.3 Closing block.**
- `AUDIT_STATUS` not in {0, 1} → print, before the existing `GATE FAIL: $ERRORS …` line:
  `GATE FAIL: the dependency audit could not be read or decided — see the error above. Nothing was decided; this is a failure to check, not a clean result.`
- Pass line names **every** check that was not performed (architect A2 — bandit's
  not-installed SKIP is the same failure-to-check as pip-audit's). Maintain an array
  `NOT_PERFORMED=()`; append `bandit SKIPPED — not installed` in bandit's existing `SKIP:` branch,
  `pip-audit NOT CHECKED — see above` when `AUDIT_STATE=not-checked`, `pip-audit SKIPPED — not
  installed` when `AUDIT_STATE=skipped`. If non-empty, the pass line is
  `GATE PASS: no blocking security issues (` + entries joined with `; ` + `)`, e.g.
  `GATE PASS: no blocking security issues (pip-audit NOT CHECKED — see above)`; otherwise the
  existing `GATE PASS: no blocking security issues`. (bandit receiving zero files in an
  `ok`/`all` changeset is not a SKIP and is not listed.)
- Exit codes unchanged: 1 if `ERRORS > 0`, else 0.
- Update the header comment: "Exit 1 = HIGH findings, dependency advisories not covered by
  the #1776 exemption roster, or an unreadable scan."

---

## 8. F4 — `requirements.txt`, and landing

### 8.1 Additions (in the file's explain-yourself style)
```
# Not imported by HOS (the App-token JWT is signed by openssl in
# bootstrap/get_app_token.sh). PyJWT arrives via semgrep and mcp; the floor exists
# so the shared oversight venv does not sit on 2.13.0's 13 advisories (#1776,
# ruling 2026-10-03). >=2.15.0 clears all 13 (PYSEC-2026-4146 affects only
# 2.11.0-2.13.0 per OSV), so no PyJWT advisory is exempted. NOTE: semgrep 1.178.0
# pins pyjwt~=2.13.0, so this floor also resolves semgrep to >=1.179.0.
pyjwt>=2.15.0

# PEP 440 ordering + PEP 503 canonicalisation for security_scan_logic.py (#1776).
# Arrives via pip-audit, but declare what we import (same rule as PyYAML above).
packaging>=23.0
```
Floors, not pins. Consumers inherit them; no new package enters a consumer venv (PyJWT and
packaging are already transitively present via semgrep/pip-audit).

### 8.2 Landing evidence (PR body, in order)
1. `scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt` (**no
   `--upgrade`**) → only semgrep → 1.179.x and PyJWT → 2.15.x change; `pip show black` still
   24.10.0.
2. `scripts/oversight/.venv/bin/pip check` clean.
3. `bash scripts/oversight/smoke_test.sh` green.
4. `bash scripts/framework/run_tests_inner_loop.sh` green. **This does not prove semgrep
   1.179 works** — `test_static_analysis_js.py` mocks `subprocess.run` and its integration test
   tolerates semgrep being absent. So also (architect A4): write a `.ts` fixture under
   `/tmp/claude/` containing `eval(userInput)`, run
   `PYTHONSAFEPATH=1 scripts/oversight/.venv/bin/python3 scripts/oversight/validators/static_analysis_js.py <fixture>`
   **before** step 1 and **after** it, and paste both outputs: same finding(s), no `error`
   field, `semgrep --version` 1.178.0 then 1.179.x.
5. `bash scripts/oversight/run_gates.sh <changed files>` → `security_scan` passes with the §6.1
   output (**AC-1**). A live pip-audit result is environment- and date-dependent, so it is
   evidence, not a pytest assertion.
6. `bash scripts/framework/regen_all.sh --check` clean.
7. PR body states the post-merge operational step (architect A5): the **Human** and
   **Overseer** clones' venvs keep PyJWT 2.13.0 until someone runs, in each clone,
   `scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt` (no
   `--upgrade`). The worker cannot do this for other clones; the human runs it. Until then
   those clones' `security_scan` stays red on PyJWT exactly as it is today (no regression).

---

## 9. Tests — `tests/oversight/test_security_scan_exemptions.py`

House style of `tests/oversight/test_secret_scan_validator_artifact.py`
(`load_module_from_path`, hermetic logic tests, gate tests that skip when the venv is absent).
Helper `_audit(*deps)` builds `{"dependencies": [...], "fixes": []}`. Logic tests pass `today`
explicitly. **No test contacts the network or depends on the live venv's package versions.**

**§15 B1/B2 amendments to this table.** These override the rows below wherever they differ.
`_NOFIX` = an injected, test-only rule
`Exemption("pyjwt", "PYSEC-2026-4146", None, date(2027,1,31), "<≥40-char test reason>", 4242)`.
It is passed as `rules=(_NOFIX,)`, or as `sl.SUPPRESSIONS + (_NOFIX,)` where black records are
also exercised. It is never added to `SUPPRESSIONS`.
- **R1:** exactly the **two** black tuples.
- **R3:** no shipped record has `package == "pyjwt"` (the floor, not the roster, handles PyJWT).
- **R4:** no shipped record has `tracking_issue == 1776`.
- **S2:** black 2120 + 2121 at 24.10.0 → 2 suppressed, status 0. **S2b (new):** `_NOFIX` with
  `fix_versions: []` → suppressed, status 0.
- **S5:** the `PyJWT`/`py_jwt` cases run under `rules=(_NOFIX,)`.
- **S7, S8:** run under `rules=(_NOFIX,)`. Expectations unchanged.
- **S9 (new):** shipped roster, `pyjwt 2.13.0 [PYSEC-2026-4146] fix_versions []` → kept,
  status 1, no note. This pins that a pre-floor venv is not exempted.
- **X5:** drop `#1997` from the failure message.
- **F9 (new, B2):** shipped roster, `black 24.10.0 [PYSEC-2026-2120]` with `fix_versions`
  missing / `"26.3.0"` / `None` / `[26]` / `{}` → each kept with `UNATTRIBUTABLE`, status 1,
  and the output names `PYSEC-2026-2120`.
- **F9b (new, B2, the direct regression):** `rules=(_NOFIX,)`, pyjwt 2.15.1 4146 with
  `fix_versions: "none"` and with `fix_versions: None` → kept `UNATTRIBUTABLE`, status 1
  (before B2 this was suppressed).
- **F9c (new, B2):** `aliases: "x"` on black 2120 at 24.10.0 → still suppressed, status 0
  (aliases stay lenient).
- **P3:** 117 deps of which 2 vulnerable (black 2120, 2121) → `117 dependencies read`,
  `2 distinct advisory(ies)`.
- **P6:** replace the pyjwt roster-line assertion with
  `black [PYSEC-2026-2121] fixed_in 26.3.1 — expires 2027-01-31 — NOT NEEDED (not reported in this environment) — #1961`.
- **G2:** stub prints black 2120 + 2121×2 only → exit 0, `2 advisory(ies) suppressed`.

| id | test | expectation |
|---|---|---|
| **Roster pins** |||
| R1 | `SUPPRESSIONS` equals exactly the two (§15 B1) `(package, advisory_id, fixed_in, expires, tracking_issue)` tuples of §4.4 | any roster edit forces a visible test edit |
| R2 | `validate_exemptions(SUPPRESSIONS) == []` | |
| R3 | the only `pyjwt` record is PYSEC-2026-4146 | the floor, not the roster, handles the other 12 |
| R4 | record 3's `tracking_issue` ≠ 1776 | |
| **Matching (AC-2)** |||
| S1 | non-roster package `requests 2.0.0 / CVE-2099-0001` | kept, status 1 — **AC-2 proof** |
| S2 | each record at a below-`fixed_in` version (black 24.10.0); pyjwt 4146 with `fix_versions: []` | suppressed, status 0 |
| S3 | black PYSEC-2026-2121 at 26.3.1 | kept, `PREMISE BROKEN` |
| S4 | pyjwt 2.13.0 PYSEC-2026-4140; black 24.10.0 with an unknown id | kept — other ids on roster packages fail closed |
| S5 | names `PyJWT`, `Black`, `py_jwt`→ no (different canonical name) | canonical variants match; different names do not |
| S6 | version `"not-a-version"` on a roster advisory | kept, `UNPARSEABLE VERSION` |
| S7 | pyjwt 4146 with `fix_versions: ["2.16.0"]` | kept, `FIX NOW AVAILABLE` naming 2.16.0 |
| S8 | pyjwt 4146 twice in one `vulns`, one with `[]`, one with `["2.16.0"]` | deduped, union non-empty → kept |
| **Expiry** |||
| X1 | `today == expires` | suppressed |
| X2 | `today == expires + 1` | kept; note has `EXEMPTION EXPIRED`, the date, `#1961` |
| X3 | `today == expires - 14` | suppressed + `EXPIRING SOON` line |
| X4 | `today == expires - 15` | suppressed, no warning |
| X5 | real UTC clock: no shipped record expired | **dated cliff**: fails from 2027-02-01, message lists lapsed records and says renewal needs a human decision (H3) |
| X6 | `expires` as `str` and as `datetime.datetime` | validation errors |
| **Fail-closed** |||
| F1 | `run_filter("not json", …)` | status 2; stderr names `JSONDecodeError` |
| F2 | root list; `dependencies` missing; not a list; `[]` | status 2 each |
| F3 | injected bad rules: short reason, non-canonical package, bad `fixed_in`, duplicate key, `tracking_issue=True` | errors; `run_filter` status 2 |
| F4 | dependency entries `None`, `0`, `""`, `[]`, `"x"` | each kept `UNATTRIBUTABLE`, status 1 |
| F5 | vuln with no `id` on `black 24.10.0` | kept — malformed never rides an exemption |
| F6 | clean audit + broken roster, active mode | status 2 |
| F7 | `vulns` not a list | kept `UNATTRIBUTABLE` |
| F8 | `main` with `partition` monkeypatched to raise | exit 2, stderr `crashed` |
| **Parsing / report (AC-3)** |||
| P1 | same `(name, version, id)` twice | `raw 2`, `distinct 1` in summary |
| P2 | same id, `["26.2"]` / `["26.2.0"]` | deduped, both shown, fixed-advisory match unaffected |
| P3 | 117-dep doc, 3 vulnerable | only 3 considered; `117 dependencies read` |
| P4 | dep with `skip_reason` | `NOT CHECKED:` line; status unaffected |
| P4b | dep with `skip_reason` **and** `vulns: [{id: CVE-2099-0002, …}]` | `NOT CHECKED:` line **and** the advisory kept, status 1 (A3) |
| P5 | suppression line has id, reason, expiry date, issue | literal assertions |
| P6 | passing run | mode + roster + suppression lines present with status 0 |
| **Scope (H2)** |||
| M1 | `tmp_path` with `bootstrap/hos_install.sh`, no `.hos-release` | ACTIVE |
| M2 | both present | INACTIVE, `.hos-release present` |
| M3 | neither | INACTIVE, `not found` |
| M4 | inactive mode + black PYSEC-2026-2121 at 24.10.0 | kept; INACTIVE mode line printed |
| M5 | `roster_mode(<this repo>)` | ACTIVE |
| **Gate (shell, via `HOS_PIP_AUDIT_BIN` stub; skip if venv absent)** |||
| G1 | stub prints a new vulnerable package, rc 1 | gate exit 1 — AC-2 end-to-end |
| G2 | stub prints only the two roster advisories (2121 twice; §15 B1), rc 1 | gate exit 0; mode line and suppression block in output |
| G3 | stub prints `{"dependencies": "x"}`, rc 0 | gate exit 1; output contains `could not be read or decided` |
| G4 | stub prints non-JSON and exits 3 | `NOT CHECKED:` line; final line `GATE PASS: … (pip-audit binary overridden; pip-audit NOT CHECKED — see above)` (§16) |
| G4c | stub: rc 0, invalid JSON, `GATE_RETRIES=1` | retried (>=2 calls); `GATE FAIL: pip-audit completed at least once but its output could not be parsed, and no attempt produced a readable scan`; non-zero exit; no NOT CHECKED (§16 rounds 2-3) |
| G4d | stub: invalid JSON first call, clean valid JSON second | retry succeeds; gate passes |
| G4e | stub: rc 0 invalid JSON first call, then exit 3 (`test_g4e_unparseable_then_execution_failure_still_fails_closed`) | sticky unparseable flag survives the later execution failure; same GATE FAIL line; non-zero exit; no NOT CHECKED (§16 round 3) |
| G4f | stub: rc 1 invalid JSON first call, then exit 124 (`test_g4f_unparseable_rc1_then_timeout_still_fails_closed`) | sticky unparseable flag survives the later timeout; same GATE FAIL line; non-zero exit; no NOT CHECKED (§16 round 3) |
| G5 | empty-changeset invocation (as in `tests/oversight/test_scan_gates_empty_args.py`) | unchanged `NOT CHECKED` behaviour, stub not invoked |
| G6 | static: `security_scan.sh` appends `bandit SKIPPED — not installed` to `NOT_PERFORMED` inside the bandit not-installed branch, and the pass line is built from `NOT_PERFORMED` | A2 (static, because hiding the venv's bandit in a subprocess test is not hermetic) |
| **Static** |||
| T1 | `security_scan.sh` contains no `|| echo "0"` | both fail-opens gone |
| T2 | `require_human_approval.matched_surfaces` with `load_globs(protected_surfaces.txt)` classifies `scripts/oversight/security_scan_logic.py` and `…/secret_scan_logic.py` as protected, and `…/prompt_audit_logic.py` and `…/retry_rescue_logic.py` as **not** protected (ADR-1935 N3 — guards against a glob creeping back) | A1 |
| T3 | `docs/AGENT-IDENTITY.md` contains both exact paths; `docs/v0.7.0/ADR-1935-protected-surface-recalibration.md` contains `scripts/oversight/security_scan_logic.py` | sync rule; ADR-1935 implementer cannot drop it |
| T4 | `requirements.txt` has `pyjwt>=2.15.0`, a `packaging` floor, and still `black>=24.0,<25.0` | guards #103 |

Gate tests pass one trivial clean `.py` file so bandit runs; G1–G4 put the stub path in
`HOS_PIP_AUDIT_BIN` via the subprocess `env`.

---

## 10. Acceptance criteria

- **AC-1** In this repo, after §8.2 step 1, `security_scan` passes; output matches §6.1.
- **AC-2** Any advisory not on the roster — new package, a new id on black, or any PyJWT id —
  fails the gate (S1, S4, S9, G1). A malformed `fix_versions` never rides an exemption (F9, F9b).
- **AC-3** Every suppression is printed with id, reason, expiry and issue on every run,
  including passing runs; the roster mode is printed every run (P5, P6, G2, M4).
- **AC-4** `pyjwt>=2.15.0` and `packaging>=23.0` declared; black pin intact; reconciled venv on
  PyJWT ≥ 2.15.0 with `pip check` clean (T4, §8.2).
- **AC-5** No fail-open on an unreadable scan: both `|| echo "0"` removed; unreadable or
  wrong-shape audit → gate failure saying it could not be read (T1, F1–F2, G3); NOT CHECKED and
  SKIP are named in the closing line (G4).
- **AC-6** `scripts/oversight/security_scan_logic.py` and `scripts/oversight/secret_scan_logic.py`
  are protected in `protected_surfaces.txt`, CODEOWNERS and AGENT-IDENTITY §9.0, and
  ADR-1935 §3.5/§4 lists the new module; no `*_logic.py` glob; `regen_all.sh --check` clean (T2, T3).
- **AC-7** In an installed consumer tree the roster is inactive and every advisory is enforced
  (M2–M4).
- **AC-8** No record already expired at merge; dated cliff present (X5).

**Build order:** S1 = F4 + T4 + §8.2 steps 1–4 (floor verified before any exemption exists);
S2 = F2 + F9 logic/scope tests; S3 = F3, F5–F8, F10, F11 + gate/static tests + §8.2 steps 5–7.

---

## 11. Follow-ups and out of scope

~~**Required before the PR (worker opens it):** one issue, "Remove the PyJWT PYSEC-2026-4146
exemption once a fixed release ships (#1776)", whose number is record 3's `tracking_issue`.~~
**Superseded by §15 B1:** that issue (#1997) is closed as not-needed, with a comment that links
§15. No follow-up issue is required. Black's renewal is owned by the existing #1961.

**Candidates to file (not blocking):** consumer-owned exemption roster (H2 follow-up);
pip-audit non-completion fail-open (TD-D8); moving bandit's inline logic into the module;
wiring `security_scan` into CI (architect's call; DECISIONS.md:787).

**Out of scope:** `ensure_venv.sh` reconcile (TD-D7); cryptography (resolved); anyio/click/
mcp/pip (resolved); the black 26 upgrade (#1961); any change to `run_gates.sh`,
`lib/changeset.sh` or workflows; a committed audit baseline (second suppression mechanism).

**DECISIONS.md entry (F10):** the two rulings, the two records and their expiry, record 3 dropped and why (§15 B1), the B2 fail-closed parse rule, the no-fix
key, the H2/H3 defaults pending human confirmation, the semgrep coupling, and the two exact
protected entries (with the reason the iteration-1 glob was dropped: ADR-1935 per-file rule).

---

## 12. Startup-gap and affected sign-offs

Not a startup-artifact gap: DECISIONS.md:787 (#1216) recorded the always-red pip-audit as
accepted debt. Iteration 1 was never implemented, so no code was reviewed against it; the
iteration-2 rescope orphans no approval. The behavioural changes to existing reviewed code
(bandit/pip-audit fail-open removal, `GATE PASS` wording) strictly tighten the gate. The
two new protected entries change approval requirements for **future** PRs touching
`secret_scan_logic.py` (one existing module; ADR-1935 already classifies it P) and the new
module; no past sign-off is invalidated. Per ADR-1935 §8's obligation, the PR body names the
last merge that modified `secret_scan_logic.py` and whether it had a human approval
(`merge_authority.sh human-approval`), for the approving human to review.

---

## 13. Architect re-review requested

1. TD-D2b, the no-fix key (`fix_versions` empty after union; no version bound).
2. TD-D7, dropping the reconcile in favour of a gate `HINT` + one-time manual install.
3. §5, the source-repo predicate (`.hos-release` absent **and** `bootstrap/hos_install.sh` a
   regular file, rooted at the module's own repo).
4. `skip_reason` dependencies printed `NOT CHECKED` but **non-blocking** — making them blocking
   would red any consumer whose venv carries a non-PyPI project package.
5. Removing the live pip-audit test and installed-version test from the suite (changelog #9).

---

## 14. Architect review — iteration 2 (2026-10-06)

**Verdict: APPROVED WITH CHANGES.** Corrections A1–A5 are **already applied in this document**
by the architect. No iteration 3 is needed; the coder implements the document as it now stands.
The verdict would be APPROVED except that A1 reverses one of my own iteration-1 rulings.

### Independent verification (not taken from the doc)
- `security_scan.sh` read in full. Both `|| echo "0"` fail-opens are where §7 says (bandit
  `HIGH_COUNT`, pip-audit `VULN_COUNT`). #672's `_run_pip_audit` predicate accepts any valid
  JSON at rc 0/1, so TD changelog #10 is correct: G3 must use well-formed JSON of the wrong shape.
- `hos_install.sh:1894-1906` copies five named `bootstrap/` files. It never copies itself, and it
  stamps `.hos-release` (`:2498-2507`). The HOS repo has `bootstrap/hos_install.sh` and has never
  had a `.hos-release` in git history. VF-5 is confirmed.
- Venv: PyJWT 2.13.0 is `Required-by: mcp, semgrep`, and mcp's only dependent is semgrep. VF-2
  is confirmed, and the record-3 wording has been tightened to match.
- `requirements.txt` declares `semgrep>=1.50` with no pin, so the floor does not conflict.
- `test_static_analysis_js.py` mocks `subprocess.run`, and its integration test tolerates a
  missing semgrep. §8.2 step 4 therefore did **not** prove semgrep 1.179 works. Fixed by A4.
- #1961 is open, but it is `priority:low` in v0.7.12. That affects H3 (below).
- **ADR-1935 (accepted 2026-10-05, after my iteration-1 ruling)** classifies
  `scripts/oversight/` files individually. It rules `prompt_audit_logic.py` and
  `retry_rescue_logic.py` U/N3, and it says the remainder of `scripts/oversight/` is "listed per
  file". The iteration-2 `*_logic.py` glob contradicts that binding ruling. Fixed by A1.

### Rulings on the five questions
1. **TD-D2b, the no-fix key: SOUND.** It keys on the premise ("no fix exists") instead of on
   fix-version strings. Because dedup unions on `(key, version, id)`, any source that reports a
   fix disables the record, so source disagreement fails closed. An advisory re-issued under a
   different id (GHSA instead of PYSEC) does not match, and also fails closed. Leaving out an
   upper version bound is correct: the justification is non-reachability, which does not depend
   on the version, and expiry provides the time box. **Residual risk:** the reachability claim
   applies to *today's* HOS. If PR authors import `jwt` later, nothing catches it except review
   and the expiry. That risk is accepted, and the roster printed on every run keeps it visible.
2. **TD-D7, dropping the reconcile: ACCEPTED.** Iteration-1 blocking item 2 is legitimately
   moot. A pre-floor venv really is vulnerable, so a red gate on it is the truth and not a false
   positive. The HINT gives the exact remedy without `--upgrade`. Adding locking and failure
   isolation to a file sourced by about 100 call sites, all to carry a single floor, costs more
   than it is worth. Gap closed by **A5**: the Human and Overseer clones need a human-run
   reconcile, and the PR body must say so.
3. **§5, the source-repo predicate: SOUND.** The two conditions are independent, and the
   installer guarantees both for consumers. A missing `.hos-release` after a failed install still
   leaves `hos_install.sh` absent. An `OSError` makes the roster inactive. Rooting at `__file__`
   rather than the cwd is correct. The dogfooding edge is now named in §5; it fails in the safe
   direction.
4. **`skip_reason` non-blocking: ACCEPTED**, and consistent with TD-D8. Blocking would turn the
   gate red for any consumer with an editable or private package, which recreates the
   always-red problem. Gap closed by **A3**: a skip marker can no longer hide a `vulns` list on
   the same entry.
5. **Live pip-audit and installed-version tests out of the suite: ACCEPTED.** A required check
   that queries a live advisory feed goes red on the next unrelated CVE. That is exactly the
   disease this issue exists to cure. The ongoing regression guards are G1/G2, which run the full
   shell+module path against a stub; §8.2 provides the one-time live evidence. M5 and X5 are the
   only environment- or date-sensitive tests, and both are deliberate.

### Iteration-1 blocking items
| # | Item | Status |
|---|---|---|
| 1 | Consumer shipping of the roster | **Addressed** (§5, AC-7, M1–M5) |
| 2 | ensure_venv reconcile sub-points | **Moot**: the mechanism was dropped (TD-D7); its operational residue is covered by A5 |
| 3 | secret_scan_logic.py hole | **Addressed, re-ruled (A1)**: two exact entries replace the glob |
| 4 | bandit fail-open / empty deps / falsy entries / skip_reason / GATE PASS text | **Addressed**; A2 extends the closing line to bandit's SKIP, and A3 closes a skip-marker hole |
| 5 | Expiry off the 22-Dec cliff | **Addressed** (2027-01-31); H3 note added |

### Semgrep 1.178 → 1.179 side effect: ACCEPTABLE
The only metadata delta is the pyjwt pin (VF-3). The floor, not a pin, means consumers' fresh
venvs already resolve the latest semgrep. The one real risk is a change in ruleset compatibility
in `static_analysis_js`. It is unproven by the suite, so A4 requires before-and-after evidence.

### Corrections applied (A1–A5)
- **A1 (supersedes my iteration-1 glob ruling).** F5/F7 now add two exact paths:
  `scripts/oversight/secret_scan_logic.py` and `scripts/oversight/security_scan_logic.py`. New
  F11 amends ADR-1935 §3.5/§4 with the new module. Without it, ADR-1935's implementer
  ("replace with §4") would silently unprotect the module, and T-1935-3 would not catch the
  loss. T2 now also asserts that the two N3 modules stay unprotected, and T3 pins the ADR-1935
  line. TD-D9, AC-6, §12 and the self-flag have been updated. §12 picks up ADR-1935 §8's
  last-merge human-approval note for `secret_scan_logic.py`.
- **A2.** The closing pass line is built from a `NOT_PERFORMED` array that includes bandit's
  not-installed SKIP (§7.3, G6).
- **A3.** A `skip_reason` entry with a non-empty `vulns` still has those vulns processed
  (§4.3, P4b).
- **A4.** §8.2 step 4 now requires a real before-and-after semgrep run through
  `static_analysis_js.py` on a `/tmp/claude/` fixture.
- **A5.** §8.2 step 7 adds the post-merge reconcile in the Human and Overseer clones.
  Separately, §7.2 step 5 now uses `"$OVERSIGHT_PYTHON"` with no `python3` fallback, because
  system python lacks `packaging` and would produce a spurious exit 2.

### Implementability
11 files, plus register and validator artifacts, which is within 15. Every output string,
exit code, matrix row and test is specified literally. I see no remaining point where a coder
has to make a design choice. The ordering S1 → S2 → S3 is correct: the floor is verified
before any exemption exists.

### Needs a human decision (at PR review; none of these block coding)
- **H2**: confirm the HOS-only roster (consumers stay red on black until a consumer-owned
  roster exists).
- **H3**: confirm 2027-01-31, and decide whether to pull #1961 forward. As scheduled
  (`priority:low`, v0.7.12) the black records will likely hit the cliff.
- **A1 load**: two files newly human-gated ahead of ADR-1935 ESC-1. This is small and
  consistent with ADR-1935's classification, but it is a human-load change the approving human
  should see.
- **Post-merge**: the human runs the reconcile command in the Human and Overseer clones (A5).

---

## 15. Architect rulings — implementation-time discrepancies (2026-10-06)

Raised by the coder against commit `2a5b474ec`. Both are binding. The sections they affect
(status, Human Review, §1 #4, VF-1, TD-D2b, TD-D10, §4.3, §4.4, §4.5, §6.1, §8.1, §9, AC-2,
§11) have been corrected in place, and the corrections cite this section.

### B1 — Record 3 (PyJWT PYSEC-2026-4146) is DROPPED

**Independent verification (architect, not taken from the coder):**
- `scripts/oversight/.venv/bin/pip-audit --format json` on the reconciled venv (PyJWT 2.15.1,
  semgrep 1.179.0) gives rc 1 and exactly three raw records: black PYSEC-2026-2121 ×2 and
  PYSEC-2026-2120. pyjwt and semgrep report `vulns: []`.
- OSV `PYSEC-2026-4146` and its alias `GHSA-gvp8-978c-rx2q` agree:
  `introduced 2.11.0, last_affected 2.13.0`, with affected versions 2.11.0, 2.12.0, 2.12.1 and
  2.13.0. Iteration 2 read pip-audit's empty `fix_versions` at 2.13.0 as "no fix exists". It
  actually reflects a `last_affected` bound with no `fixed` event. VF-1's premise was wrong.

**Why the record goes, rather than staying as harmless insurance:**
1. **It cannot change any outcome.** At or above the floor, the advisory is not reported. Below
   the floor, PyJWT 2.11–2.13 carries 12 other advisories that fail the gate, so suppressing
   4146 never turns red into green. An exemption that can never decide anything is pure
   surface: one more record to renew, to explain, and to trip the 2027-02-01 cliff (X5).
2. **Its justification is now false.** The reason text says "no fixed release exists". A
   visible exemption whose printed justification is untrue is worse than no exemption. AC-3's
   visibility guarantee is only worth something if what it shows is true.
3. **Dropping it only narrows suppression.** The human authorized *up to* one PyJWT exemption.
   Shipping zero is strictly tighter, so this is not a product-boundary change that needs
   pre-clearance. The deviation from the 2026-10-03 wording must still be stated in the PR body
   (see Human Review Required).

**The no-fix key (TD-D2b) is KEPT**, with no shipped user. Reasons: it is already reviewed and
it fails closed. The 2026-10-02 ruling contemplates no-fix exemptions as a class. Removing it
would force the next genuine no-fix case to be re-designed under time pressure. It stays
covered by tests through the injected `_NOFIX` rule (§9 amendments). With B2 in place, its one
fail-open path is closed.

**#1997** is closed as not-needed by the worker, with a comment that links this section.

### B2 — malformed `fix_versions` is a malformed advisory (fail closed)

**Defect confirmed.** In `_str_tuple`, coercing a non-list-of-strings to `()` (`security_scan_logic.py`,
`_parse_vulns`) made malformed equal "no fix reported". That satisfies TD-D2b condition (3′),
so a corrupted or schema-drifted audit record could be *suppressed* by a no-fix rule. TD-D6
forbids that: a failure to decide must never pass. The iteration-2 §4.3 text that said
"coerced to `()`" was the design defect, not the coder's.

**Ruling.**
- `fix_versions` is decision-bearing. Missing, or present but not a `list[str]`, makes the vuln
  malformed (`malformed_why` per §4.3). It is kept by partition row 1 (`UNATTRIBUTABLE`) and is
  never deduplicated. The malformed advisory carries the vuln's real `id` so the output names
  it. `[]` remains valid.
- "Missing" is malformed too, not just "wrong type". pip-audit's JSON format always emits the
  key, so absence means the producer is not the format we parse. Unknown is not "none".
- `aliases` stays lenient (coerced to `()`). It is display-only (TD-D3), so leniency cannot open
  anything. Being strict there would only add red-gate risk on a harmless format drift.
- This applies to every advisory, not only ones that match a no-fix rule. One parse rule is
  simpler to verify than a rule that depends on context, and any real pip-audit output is
  unaffected.

### Affected sign-offs (startup-gap check)

Not a `startup-artifact-gap`. The initial review could not have caught B1 without the
OSV-versus-pip-audit cross-check that only this implementation surfaced, and B2 is a design
defect found at implementation. **No code-review or reviewer sign-off exists yet for #1776's
implementation** (the only register entry is the 2026-09-23 iteration-1 technical-design
sign-off, already superseded by iteration 2). So no approval is orphaned. The §14 design
approval stands as amended here. Every reviewer runs against the post-B1/B2 code.

### Loop state
This is a ruling on escalated discrepancies, not a design-critique round, so the round counter
is unchanged (iteration 2, approved). No architect temp-state file is open.

## 16. Review-fix (security-reviewer SHOULD_FIX)

When `HOS_PIP_AUDIT_BIN` is set non-empty, the pip-audit section prints `NOTE: pip-audit binary overridden by HOS_PIP_AUDIT_BIN=<path>` and adds `pip-audit binary overridden` to `NOT_PERFORMED`, so the closing `GATE PASS` line names it (amends §7 and test G4; new test G4b). No verdict or exit code changes. `secret_scan.sh` is a follow-up.

### Second-review findings (codex CWE fail-open / agy logic-error)

- **Codex (fail-open, verified by reproduction).** `parse_audit` counted structurally incomplete dependency entries (`{}`, no `vulns`, no `name`/`version`) as audited, so `filter` returned rc 0 "OK". A dependency now counts as AUDITED only if `name` and `version` are non-empty strings and `vulns` is a list. A `skip_reason` entry keeps its NOT CHECKED handling (non-blocking; any `vulns` list on it is still processed, §A3). Any other entry is kept as UNATTRIBUTABLE via `_malformed` with the reason `dependency entry is incomplete: <fields>` (status 1; the gate fails). Tests F10, F10b, F10c; P3 fixture corrected (it relied on a `vulns`-less entry being clean). Matrix §4.5 malformed row amended.
- **agy (logic-error, verified by reading).** `_run_pip_audit` returned `${prc:-1}`, i.e. 0, when pip-audit exited 0 with unparseable output, so `run_with_retry` read a corrupt scan as success (no retry; the module then exited 2, still fail-closed, but the retry/NOT CHECKED contract was bypassed). It now returns 1 for rc 0/1 with invalid JSON (124 still passes through), so the attempt is retried and, once exhausted, reports `NOT CHECKED`. Test G4c (stub: rc 0, invalid JSON, `GATE_RETRIES=1` -> at least 2 invocations, NOT CHECKED, exit 0) (superseded by rounds 2–3 below). No change to the §4.5 exit codes: an unparseable scan never reaches the module.

### Second-review round 2: codex CWE-636 (fail-open regression, verified by reproduction)

The agy fix above (return 1 on rc 0/1 with invalid JSON) turned a fail-closed path into a fail-open one: when every attempt produced corrupt output, `run_with_retry` exhausted with `required=false`, so the gate printed `NOT CHECKED` and exited 0, whereas previously the corrupt rc-0 output reached the module (exit 2, GATE FAIL). Fix: `_run_pip_audit` resets a global `_PIP_AUDIT_UNPARSEABLE` to 0 at the start of each attempt and sets it to 1 on the rc 0/1 invalid-JSON branch (`run_with_retry` calls the function in the same shell, so the global persists). In the retries-exhausted branch, if the flag is set the gate prints `GATE FAIL: pip-audit completed but its output could not be parsed after <n> attempt(s) …` and increments `ERRORS`; otherwise (timeout / network, rc not in {0,1}) the TD-D8 `NOT CHECKED` behaviour is unchanged. A later successful retry proceeds normally. The flag is unset beside `unset -f _run_pip_audit`. Tests: G4c now asserts non-zero exit plus the GATE FAIL line (stub called >=2 times); G4d (corrupt then clean) passes; G4 (timeout -> NOT CHECKED) unchanged. Matrix §4.5 and §6 step 4 amended.

### Second-review round 3: codex CWE-636 (mixed-failure sequence, verified by reproduction)

Round 2 reset `_PIP_AUDIT_UNPARSEABLE` at the start of every attempt, so "attempt 1: rc 0/1 with unparseable output, attempt 2 (last): timeout or execution failure" ended with the flag 0 and the gate reached the NOT CHECKED (pass) branch, erasing evidence that a completed scan produced unreadable output. The flag is now sticky: initialised to 0 once before `run_with_retry`, never reset inside `_run_pip_audit`, set to 1 on the rc 0/1 invalid-JSON branch. A later successful parsed retry still proceeds normally (the success branch ignores the flag). In the retries-exhausted branch, a set flag prints `GATE FAIL: pip-audit completed at least once but its output could not be parsed, and no attempt produced a readable scan (<n> attempt(s)) …` and increments `ERRORS`; an unset flag keeps TD-D8 NOT CHECKED. Tests: G4e (rc 0 invalid JSON then exit 3) and G4f (rc 1 invalid JSON then 124) fail the gate with no NOT CHECKED; G4c wording updated; G4, G4d unchanged. Matrix §4.5 and §6 step 4 reworded.

### Full-range second review (agy spec-adherence / codex CWE-693)

- **agy spec-adherence.** `run_filter` relied on the caller to pass an empty roster when the mode is inactive. It now computes `effective_rules = rules if mode.active else ()` and uses that for validation, partition and render, so H2 holds regardless of caller. Test M6 passes the shipped roster with an INACTIVE mode: the advisory is kept, status 1, output shows `Exemption roster: INACTIVE`.
- **codex CWE-693.** The PYSEC-2026-2121 exemption rests on HOS never setting black's `python-cell-magics`; PYSEC-2026-2120 rests on no workflow using the Black GitHub Action. Nothing enforced either premise. New tests: PR1 (`pyproject.toml [tool.black]` has neither `python-cell-magics` nor `python_cell_magics`; pyproject.toml is the only config black reads from the repo root), PR2 (no black invocation in `lint_check.sh` passes `--python-cell-magics`), PR3 (no `.github/workflows` file references `psf/black`). Failure messages say the premise no longer holds and direct removal of the exemption (upgrade black, #1961) rather than editing the test. Both records' `reason` strings gain one sentence naming the enforcing tests (reasons are not pinned by R-tests beyond the minimum length).
