# TECHNICAL DESIGN — #1776: `security_scan` dependency-advisory exemptions, and the `cryptography` bump

**Issue:** #1776 (`bug`, `process-gap`, `priority:critical`, milestone v0.7.0 — Quality)
**Branch:** `worker-1776-security-scan-exemptions-260923074001-877483`
**Status:** DRAFT — iteration 1. Awaiting architect review. Three residual items are flagged
for architect/human decision in §12 (**RISK-1**, **RISK-2**, **RISK-3**); everything else is settled.
**Change classification:** `structural` for the suppression policy itself (what a *blocking
security gate* stops blocking on) — **pre-authorized by the human ruling of 2026-09-23 on
#1776**, quoted in full below and not re-litigated here. `additive` for the logic module, the
`cryptography` floor, the venv reconcile step and the tests.

## HOS self-flag

```
RISK: MEDIUM
CONFIDENCE: HIGH on the module contract, the keying rule, the fail-closed matrix and the test
            plan (all derived from a live pip-audit run and a direct read of the #1754
            precedent). MEDIUM on the venv-reconcile mechanism (§7), which is new machinery
            rather than a copy of an existing pattern. LOW-CONFIDENCE claim isolated and
            flagged: the human ruling's stated reachability premise for `cryptography` does
            not match the code (§0, TD-VF-6) — the ruling's *decision* is implemented
            unchanged; the premise correction is reported, not acted on.
BLAST RADIUS: scripts/oversight/gates/security_scan.sh (PROTECTED SURFACE — human approval
            required), a new scripts/oversight/security_scan_logic.py, scripts/oversight/
            requirements.txt, scripts/oversight/ensure_venv.sh, scripts/framework/
            protected_surfaces.txt + generated .github/CODEOWNERS, new tests. The shared
            oversight venv is mutated (cryptography 49 → 50) — every gate, validator and
            agent CLI runs in it.
```

### Human Review Required

- The suppression policy is `structural` and touches a protected surface
  (`scripts/oversight/gates/**`). The PR **must** carry a human approval; no bot approval
  counts.
- **RISK-1 (§12):** the ruling's factual premise for `cryptography` is wrong in a way that
  makes the bump *safer*, not riskier. Reported for the record; the ruled action is
  implemented as ruled. No decision is being requested to change it — only an acknowledgement
  that the premise correction was surfaced rather than buried.
- **RISK-2 (§12):** choice of expiry date (2026-12-22) and the single-cliff-vs-staggered
  question.
- **RISK-3 (§12):** `black`'s exemption cannot be renewed indefinitely without either a
  formatter migration (#103) or a permanent decision. Named now so the December review is not
  a surprise.

---

### Rulings applied (not re-litigated)

The human ruling on #1776, 2026-09-23 (comment by `scottthurlow-claude[bot]`, human-authored),
is the authority for §§1–3. Its two operative parts:

| Ruling | Effect on this document |
|---|---|
| **R1** — `cryptography` 49.0.0 → 50.0.0: **bump it for real**, with the full inner-loop suite green against the bumped version before landing. Not a blind bump. | §7 (requirements floor + venv reconcile), §9 TC-E1/TC-E2, §10 AC-4 evidence. `cryptography` is **forbidden** from the exemption roster, and a test pins that (§9 TC-S7). |
| **R2** — the other five (`anyio`, `black`, `click`, `mcp`, `pip`): **time-boxed, visible exemptions**, using **#1754's mechanism exactly** rather than a second suppression mechanism. Each must name the CVE, the reason and an expiry **in the gate's own output** — never a silent pass. And they must not be left permanently red either. | §§4–6 (the module), §6.4 (output contract), §5 (roster). No blanket `pip-audit` skip anywhere in this design. |

Two things the ruling does **not** settle, and which this document therefore decides (open to
architect override): the exemption **keying rule** (§4.2, TD-D2) and the mechanism by which an
already-built venv picks up the new floor (§7, TD-D7).

---

## 0. Verification findings — probed, not assumed

Re-derived on 2026-09-23 against the working tree at
`worker-1776-security-scan-exemptions-260923074001-877483`. Every behavioural claim below was
run, not recalled. **The issue's table is stale in two ways and must not be copied verbatim
into code** (TD-VF-1, TD-VF-2).

### TD-VF-1 — the live audit reports **17 raw records but only 11 distinct advisories**

`scripts/oversight/.venv/bin/pip-audit --format json` (exit 1), parsed:

| package | installed | advisory id | fix_versions reported | aliases |
|---|---|---|---|---|
| anyio | 4.14.0 | CVE-2026-63374 | 4.14.2 | GHSA-82r6-8w77-94w6 |
| anyio | 4.14.0 | CVE-2026-64847 | 4.14.2 | GHSA-5p39-cfhj-2xmp |
| anyio | 4.14.0 | CVE-2026-63349 | 4.14.2 | GHSA-3w57-8xmc-8v26 |
| black | 24.10.0 | PYSEC-2026-2121 | 26.3.1 | CVE-2026-32274, GHSA-3936-cmfr-pm3m |
| black | 24.10.0 | PYSEC-2026-2120 | 26.3.0 | CVE-2026-31900, GHSA-v53h-f6m7-xcgm |
| click | 8.1.8 | PYSEC-2026-2132 | 8.3.3 | CVE-2026-7246, GHSA-47fr-3ffg-hgmw |
| cryptography | 49.0.0 | PYSEC-2026-3552 | 50.0.0 | CVE-2026-69247, GHSA-g6cj-pr64-35w5 |
| mcp | 1.23.3 | PYSEC-2026-3481 | 1.27.2 | CVE-2026-52870, GHSA-hvrp-rf83-w775 |
| mcp | 1.23.3 | PYSEC-2026-3482 | 1.27.2 | CVE-2026-52869, GHSA-jpw9-pfvf-9f58 |
| mcp | 1.23.3 | PYSEC-2026-3483 | 1.28.1 | CVE-2026-59950, GHSA-vj7q-gjh5-988w |
| pip | 26.1.2 | PYSEC-2026-3721 | **26.2 *and* 26.2.0** | CVE-2026-13346, GHSA-qwm4-qh6w-59xr |

Six of the 17 raw records are **duplicates within a single dependency's `vulns` list**
(`black` PYSEC-2026-2121 ×2, `cryptography` PYSEC-2026-3552 ×2, each `mcp` advisory ×2, `pip`
PYSEC-2026-3721 ×2). There are **no duplicate dependency records** — `dependencies` holds 117
entries, all distinct on `(name, version)`. The duplication is inside `vulns`, from pip-audit
merging two advisory sources.

Two consequences, both binding on the design:

1. Counting raw records overstates the problem (17 vs 11) and would make the gate's output
   disagree with a human reading the advisory list. **§4.4 requires deduplication on
   `(canonical name, version, advisory id)`, with both counts printed.**
2. The same advisory id arrives with **different `fix_versions` strings from different
   sources** (`pip`: `26.2` vs `26.2.0`). **`fix_versions` and `aliases` are therefore
   unusable as any part of an exemption key** (§4.2, TD-D3).

### TD-VF-2 — a *fresh* venv would not reproduce this list; the local venv is stale

`pip index versions` on 2026-09-23, against what `requirements.txt` would resolve to today:

| package | installed here | latest available | pinned by requirements.txt? | still vulnerable at latest? |
|---|---|---|---|---|
| anyio | 4.14.0 | 4.15.1 | no (transitive: httpx, mcp, sse-starlette, starlette) | **no** (fix 4.14.2) |
| click | 8.1.8 | 8.5.0 | no (transitive: black, mutmut, semgrep, uvicorn) | **no** (fix 8.3.3) |
| mcp | 1.23.3 | 2.2.0 | no (transitive: semgrep — semgrep's own constraint decides) | **no** (fixes 1.27.2 / 1.28.1) |
| pip | 26.1.2 | 26.2.1 | no (venv bootstrap; `_create_venv` runs `pip install --upgrade pip`) | **no** (fix 26.2) |
| black | 24.10.0 | 26.5.1 | **yes — `black>=24.0,<25.0` (#103)** | **yes** (fixes 26.3.0/26.3.1, both above the pin) |
| cryptography | 49.0.0 | 50.0.1 | no (orphan — see TD-VF-6) | **no** (fix 50.0.0) |

This is the single most consequential finding in this section. It means:

- The installed versions are **not** a stable fact about the project. Four of the five
  exempted packages are unpinned transitives whose resolved version differs between this
  machine's months-old venv and a venv built today. **An exemption keyed on an exact installed
  version would silently stop matching on one machine and re-red the gate on another, for a
  package the ruling already exempted** — restoring the exact always-red disease #1776 exists
  to cure. §4.2 TD-D2 decides the keying rule on this evidence.
- `black` is the only one of the five that is *structurally* stuck: #103 pins it below the
  version that carries the fix, deliberately. Its exemption is the one that will still be
  needed at expiry (RISK-3).
- Exemption records for the other four will frequently be **inert** (no matching advisory
  reported) rather than applied. The output contract (§6.4) therefore prints the whole roster
  with per-record applied/not-applied status, so an inert record is visible rather than
  invisible.

### TD-VF-3 — `security_scan` is **not** wired into CI; it runs only via `run_gates.sh`

`.github/workflows/oversight-gates.yml:64-68` excludes it explicitly:

> `security_scan` (pip-audit against the CI venv's installed dependency versions, not the PR's
> changed files) and `collection_integrity` … are deliberately not wired in here — see
> DECISIONS.md's 2026-09-10/11 #1216 entries.

`DECISIONS.md:787` records the same deferral and even names the two remedies ("upgrade the
flagged deps first, or gate on a diff of the audit output"). `scripts/oversight/run_gates.sh`
discovers gates by `find "$GATES_DIR" -maxdepth 1 -name "*.sh"`, so `security_scan.sh` **is**
run — and is blocking — in every local/worker `run_gates.sh` invocation.

Consequences: (a) this is recorded technical debt being paid, not a startup-artifact gap
(§11); (b) the blast radius of an expiry cliff is the worker's pre-PR gate run and local
developer runs, not the merge queue; (c) re-wiring `security_scan` into CI is **out of scope**
here (§13) but becomes *possible* for the first time once this lands — flag for the architect
as a natural follow-up.

### TD-VF-4 — `ensure_venv.sh` reads `requirements.txt` **only when it builds the venv**

`scripts/oversight/ensure_venv.sh` installs requirements in `_create_venv()`, which runs only
when `$OVERSIGHT_PYTHON` is absent, when the shebang is stale (repo moved), or when the smoke
test (`import radon, bandit, flake8, tree_sitter, tree_sitter_typescript, semgrep`) fails. On
an existing, healthy venv, `requirements.txt` is **never re-read**. Adding
`cryptography>=50.0.0` to the file therefore does nothing at all on any machine whose venv
already exists — including this worker clone. §7 exists because of this.

### TD-VF-5 — CI builds a fresh venv per job; there is no venv cache

Every job in `oversight-gates.yml`, `oversight-validators.yml` and `tests.yml` runs
`bash scripts/oversight/ensure_venv.sh` after `actions/setup-python`; `grep -n "actions/cache"
.github/workflows/*.yml` returns nothing. So CI *does* pick the floor up automatically, and
§7's reconcile is needed for long-lived local/worker clones, not for CI.

### TD-VF-6 — `cryptography` does **not** sign the App-token JWT, and nothing in the venv depends on it

The ruling's premise is that `cryptography` "signs the JWT used to mint GitHub App
installation tokens (`bootstrap/get_app_token.sh`)". The code says otherwise:

```
bootstrap/get_app_token.sh:114
# ── JWT generation (RS256 via openssl — no Python crypto dep) ─────────────────
```

`generate_jwt()` shells `openssl dgst -sha256 -sign`. Corroborating probes:

- `grep -rn "import jwt\|from cryptography" --include=*.py scripts/ bootstrap/ bin/ tests/` →
  **no hits outside `scripts/oversight/.venv/`**. No HOS code imports either.
- `pip show cryptography` → `Required-by:` is **empty**. It is an orphan top-level install, not
  a transitive of anything currently in the venv. `pip list --not-required` lists it alongside
  the declared tools.
- `PyJWT` *is* present (via `mcp` ← `semgrep`) and `jwt/algorithms.py` imports `cryptography`
  for RS256 — so the capability exists in the venv, but no HOS code path reaches it.

**This does not change the decision.** R1 is implemented exactly as ruled. What it changes is
the *risk assessment*: because nothing depends on `cryptography`, bumping 49 → 50 cannot break
a dependent, which makes the bump strictly safer than the ruling assumed. It also means the
package is a candidate for removal rather than a floor — **which this design does not do**, as
that would be re-litigating a human ruling. Recorded as RISK-1 (§12) for the human's
information only.

### TD-VF-7 — the precedent's exact shape, confirmed by reading it

`scripts/oversight/secret_scan_logic.py` + `scripts/oversight/gates/secret_scan.sh:141,180`:

- invocation is `echo "$BASELINE" | PYTHONSAFEPATH=1 "$PARSE_PY" "$SCAN_FILTER" filter`, with
  `PARSE_PY="${OVERSIGHT_PYTHON:-python3}"` and `SCAN_FILTER="$_GATES_DIR/../secret_scan_logic.py"`;
- an explicit `SUPPRESSIONS: tuple[Suppression, ...]` of multi-condition `NamedTuple` records,
  each carrying its own `reason`;
- `partition_findings(...) -> (kept, suppressed)`, **pure** — all I/O is injected or lives in
  the CLI shim;
- suppressions are printed **first and always**, including on a passing run, and the count is
  repeated in the summary line;
- exit `0` clean / `1` findings survive / `2` unparseable, with the shell distinguishing 2 from
  1 in its own summary text;
- a `HOS_DETECT_SECRETS_BIN` seam (Ruling H of #1754), off by default, exists purely so a test
  can point the gate at a stub binary.

All six properties are mirrored here (§§4–6, §9).

### TD-VF-8 — `scripts/oversight/gates/**` is a protected surface; the logic module beside it is not

`scripts/framework/protected_surfaces.txt` lists `scripts/oversight/gates/**` but not
`scripts/oversight/*.py`. So under the #1754 shape the *thin caller* is human-gated while the
*decision logic* — here, the exemption roster and its expiry dates — is not. §8 TD-D9 closes
that for this module.

### Verification gaps I could not close

- **G1.** I did not build a throwaway venv from `requirements.txt` to observe the actual fresh
  resolution (semgrep alone is ~480 MB; `_EVENV_MIN_FREE_KB` is ~1 GB). TD-VF-2 infers the
  fresh resolution from `pip index versions` plus the declared pins. If the coder can afford
  the build, confirming it is cheap insurance — but the design does not depend on it, because
  §4.2's keying rule is correct under either resolution.
- **G2.** `semgrep`'s own constraint on `mcp` is unknown, so I cannot say whether a fresh venv
  gets `mcp` 1.28.1+ (fixed) or stays on a vulnerable 1.2x. The design is indifferent: the
  exemption applies iff pip-audit still reports the advisory below the recorded `fixed_in`.
- **G3.** Whether pip-audit's duplicate-record behaviour (TD-VF-1) is stable across versions.
  The design treats duplicates as *possible*, never as *guaranteed*, so either behaviour is
  handled.

---

## 1. What this slice delivers

1. `scripts/oversight/security_scan_logic.py` — a new, unit-testable module that owns every
   decision the pip-audit half of the gate makes: parse, deduplicate, apply the exemption
   roster, check expiry, report, and set the exit status.
2. A `SUPPRESSIONS` roster of **ten records across the five ruled packages** (`anyio` ×3,
   `black` ×2, `click` ×1, `mcp` ×3, `pip` ×1 — one record per advisory; §5), each naming the
   advisory, a reason, a `fixed_in` bound, an expiry date and a tracking issue.
3. `scripts/oversight/gates/security_scan.sh` reduced to a thin caller for the pip-audit half:
   the two inline `python3 -c` snippets are replaced by one invocation of the module, and the
   shell's only remaining job is mapping the module's exit status to `ERRORS` and a summary
   line.
4. `cryptography>=50.0.0` added to `scripts/oversight/requirements.txt`, plus the
   `packaging>=23.0` declaration the module needs (§4.3).
5. `ensure_venv.sh` gains a **requirements-drift reconcile** so an existing venv picks up a
   changed floor (§7) — without floating anything that is already satisfied.
6. `scripts/oversight/security_scan_logic.py` added to
   `scripts/framework/protected_surfaces.txt`, with `.github/CODEOWNERS` regenerated (§8).
7. Tests (§9) covering all four acceptance criteria, with AC-2 proven by a synthetic payload,
   not by inspection.
8. A `DECISIONS.md` entry and a follow-up issue that owns the December renewal (§10.5).

### What it deliberately does not deliver

See §13 for the full list with reasons. The headline exclusions: the **bandit** half of the
gate keeps its inline shell logic; `security_scan` is **not** wired into CI; pip-audit's
`required=false` fail-open on a network failure is **not** changed; no other package is
bumped.

---

## 2. Component map

| # | Component | Path | Change | Protected? |
|---|---|---|---|---|
| C1 | Advisory-exemption logic module | `scripts/oversight/security_scan_logic.py` | **new** | yes, after §8 |
| C2 | Security gate | `scripts/oversight/gates/security_scan.sh` | modified (pip-audit branch only) | **yes** |
| C3 | Oversight requirements | `scripts/oversight/requirements.txt` | `cryptography>=50.0.0`, `packaging>=23.0` | no |
| C4 | Venv manager | `scripts/oversight/ensure_venv.sh` | requirements-drift reconcile | no |
| C5 | Protected-surface list | `scripts/framework/protected_surfaces.txt` | one line added | **yes** |
| C6 | Generated CODEOWNERS | `.github/CODEOWNERS` | regenerated from C5 | **yes** (generated — via `scripts/framework/regen_all.sh`) |
| C7 | Tests | `tests/oversight/test_security_scan_exemptions.py` | **new** | no |
| C8 | Decision record | `DECISIONS.md` | append-only entry | no |

Data flow (pip-audit half only; the bandit half is untouched):

```
pip-audit --format json ──▶ $PIP_AUDIT_TMP ──▶ C1 `filter` (stdin)
                                                  │
                        ┌─────────────────────────┼─────────────────────────┐
                        ▼                         ▼                         ▼
                   exit 0 (clean,           exit 1 (advisories        exit 2 (unreadable
                   possibly with            survived suppression)     audit / malformed
                   suppressions)                                      roster)
                        │                         │                         │
                        └──────────────▶ C2 maps status to ERRORS + summary text
```

---

## 3. Decisions

### TD-D1 — the exemption roster is an **in-module tuple**, exactly as #1754

`SUPPRESSIONS` is a module-level `tuple[Exemption, ...]` in `security_scan_logic.py`. No YAML,
JSON or `.txt` sidecar.

Why (and why any deviation would need architect sign-off): R2 says reuse #1754's mechanism
*exactly*. Beyond obedience, three technical reasons hold independently. (a) A data file needs
a loader, and a loader has failure modes — missing file, unreadable file, wrong schema — each
of which is a new way for a security gate to decide nothing; an in-module tuple cannot fail to
load without the module failing to import. (b) A Python literal is type-checked by `mypy` and
validated at import, so a malformed record is caught by the type checker and the test suite
rather than at gate time. (c) A data file is a *configuration* surface, which invites the
reflex "just add a line"; a code surface goes through code review. §8 TD-D9 adds the human gate
on top.

### TD-D2 — **keying: `(canonical package name, advisory id)` plus a closed upper version bound `fixed_in`**

An exemption matches a reported advisory iff **all** of:

1. `canonicalize_name(dependency.name) == canonicalize_name(record.package)` (PEP 503), and
2. `vuln.id == record.advisory_id` — exact string equality on the canonical `id` field, and
3. `Version(dependency.version) < Version(record.fixed_in)` (PEP 440 ordering), and
4. `today <= record.expires`.

Any condition failing means the advisory is **kept** and the gate fails.

**Why not `(package, exact installed version, advisory id)`**, which is narrower on its face:
TD-VF-2 is the answer. Four of the five exempted packages are **unpinned transitives**. Their
resolved version is a property of *when and where the venv was built*, not of the project. An
exact-version key would be satisfied on this stale clone and unsatisfied on a venv built
tomorrow that resolves `anyio` 4.14.1 — still vulnerable, still exempt by the ruling, but now
red, with no action a developer can take except editing the roster. That is #1776 recurring
under a new name, bought for no security gain: **the justification the human accepted is
reachability, which does not vary with the patch version inside the vulnerable range.**

**Why the bound is not a security loss.** Condition 3 is closed above by the advisory's own
published fix version, so:

- the record is **provably inert** once the environment is fixed — the very upgrade that
  "should have invalidated it" is what stops it matching (the task's first hard requirement);
- it cannot reach a version the advisory does not cover, because `fixed_in` is exactly the
  boundary of coverage;
- condition 2 means a **different** advisory for the same package is never suppressed (the
  task's second hard requirement);
- and condition 1 uses PEP 503 canonicalisation so `Pip`/`pip`/`PIP` and `foo-bar`/`foo_bar`
  cannot be used to smuggle a near-miss name past a case-sensitive compare.

**Premise check, and what happens when it breaks.** `fixed_in` is a *declared claim* about the
advisory, independent of what pip-audit reports. If pip-audit reports the advisory for an
installed version `>= fixed_in`, the record's premise is false — the advisory's scope changed,
or the recorded fix version was wrong. The module must **not** suppress, and must print a
distinct, named diagnostic:

```
  PREMISE BROKEN: exemption for <pkg> [<id>] declares fixed_in=<f>, but pip-audit reports
  the advisory at installed <v> (>= <f>). The record's justification no longer holds —
  re-check the advisory and update or remove the record (#<issue>).
```

This is the TD-VF-7 / `GitShaVerifier` lesson applied: a suppression that stops working must
*say* it stopped working, and must distinguish "the environment moved" from "the finding is
real".

### TD-D3 — `fix_versions` and `aliases` are **never** part of the key, and never trusted

TD-VF-1 observed the same advisory arriving with `fix_versions: ["26.2"]` and
`["26.2.0"]` from two sources. Keying on either would make the match depend on which source
pip-audit consulted. Aliases are worse: a single advisory carries a CVE, a GHSA and sometimes a
PYSEC id, and the set is not stable over time. The record's `fixed_in` is **authored by a
human from the advisory**, checked by review, and compared with PEP 440 ordering — it is not
read from the tool's output at all. `fix_versions`/`aliases` are used only for *display*.

### TD-D4 — expiry is a `datetime.date` **literal in the record**, and `today` is **injected**

The `Exemption.expires` field holds a `datetime.date(2026, 12, 22)` object, not a string. This
eliminates an entire class of runtime failure (unparseable date) by construction: a malformed
date is a `TypeError` at import and a test failure, never a gate-time surprise.

`today` is a parameter of the pure partition function. The **CLI shim is the only place that
reads a clock**, and it reads it as `datetime.datetime.now(timezone.utc).date()` — UTC, so the
gate's verdict does not depend on the runner's timezone.

**There is no `--today` flag and no `HOS_..._TODAY` environment override.** Either would be a
suppression-extension backdoor: `--today 2020-01-01` revives every expired exemption, from
argv, on a security gate, invisibly. Tests control time by calling the pure function with an
explicit `today` (§9.1), which is strictly more capable than a flag and carries none of the
risk.

### TD-D5 — expiry behaviour: **kept, with a named, unambiguous reason**

On or before `expires`, a matching advisory is suppressed. **After** `expires`, the advisory is
kept — the gate fails — and the kept line says why in the record's own words:

```
  anyio 4.14.0 [CVE-2026-63374] fix: 4.14.2
    EXEMPTION EXPIRED 2026-12-22 (today 2026-12-23) — tracked in #<issue>.
    Original justification: <reason>.
    Renew with a fresh human decision, or upgrade the package. Do NOT extend the date
    without one.
```

The comparison is `today <= expires` — the exemption is valid *through* its expiry date and
lapses the following day.

The gate also **warns before it blocks**: within `_EXPIRY_WARN_DAYS = 14` of an expiry, a
still-valid suppression prints an additional `EXPIRING SOON` line. A time box that fires with
no warning is a time box that fires as an outage; a two-week runway makes renewal a scheduled
task.

### TD-D6 — every failure to *decide* is a gate failure (exit 2), never a pass

The fail-closed matrix, in full, is §4.5. The governing rule is #1750/#1759/#1643: a gate must
never report a pass for a check it did not actually perform. Concretely, the current shell has
exactly that bug twice — `|| echo "0"` around both `python3 -c` snippets means an unparseable
pip-audit JSON counts **zero** vulnerabilities and the gate passes. Removing that is not a
side-effect of this change; it is part of it.

### TD-D7 — the new floor reaches existing venvs through a **requirements-fingerprint reconcile**

See §7 for the mechanism. Alternatives rejected:

- *Document a manual `pip install -U -r requirements.txt`.* Relies on every human and every
  autonomous clone remembering. The worker clone would stay on `cryptography` 49 indefinitely
  and the gate would stay red on exactly the package the ruling said to fix — the failure this
  issue is about.
- *Add `cryptography` to `_smoke_test_venv`'s import list.* Would trigger a **full venv
  rebuild** (`rm -rf "$VENV"`) on version drift — a ~480 MB reinstall as the remedy for a
  one-package upgrade, and it cannot express a *version* floor at all, only importability.
- *Let the gate itself be the enforcement.* It partly is: with no exemption for
  `cryptography`, a stale venv fails the gate loudly and correctly (the environment genuinely
  is vulnerable). But a gate failure whose only remedy is undocumented is the shallow-clone
  lesson from #1754 — so the reconcile is the fix and the gate is the backstop, and the gate's
  failure text names the remedy (§6.4).

### TD-D8 — `run_with_retry`'s `required=false` fail-open on pip-audit is **kept**, and named

Today, if pip-audit times out or the network is down, the gate prints `WARN: pip-audit did not
complete` and **passes**. That is a fail-open, and it is adjacent to this issue but not this
issue: making it blocking would trade "always red from stale advisories" for "always red when
offline", which needs its own human ruling (offline local runs are normal). This slice
therefore changes only the *vocabulary*, to the #1759 `NOT CHECKED` idiom:

```
NOT CHECKED: pip-audit did not complete after retries — the dependency audit was NOT
             performed. This is a failure to check, not a clean result.
```

and records the residual as a follow-up issue (§10.5). Silent scope creep on a protected
surface is worse than an honestly-named residual.

### TD-D9 — the logic module joins the protected-surface list

`scripts/oversight/security_scan_logic.py` is added to
`scripts/framework/protected_surfaces.txt`. Rationale in §8.

### TD-D10 — the exemption is **environment-scoped**, and that boundary is stated, not papered over

pip-audit audits the *installed environment*, not the diff. So if a PR newly introduces a
direct dependency on, say, `anyio==4.14.0`, the existing `anyio` exemption suppresses its
advisories — the gate cannot tell a newly-introduced `anyio` from the pre-existing transitive
one. AC-2 is satisfied for any package **not on the roster** (which is every package in the
index except five), and the roster is printed in full on every run so the five are never
invisible. Widening this would require diffing the audit output against a committed baseline —
explicitly out of scope (§13), and named as such rather than left as an unstated assumption.

---

## 4. C1 — `scripts/oversight/security_scan_logic.py` (the contract)

### 4.1 File-level rules

- Module docstring states the problem (#1776), the ruling it implements, why suppression is
  advisory-level rather than a pip-audit skip, the visibility guarantee, and the purity
  boundary — matching `secret_scan_logic.py`'s density. Comment density in the `SUPPRESSIONS`
  block must match the precedent's: every record explains *itself*.
- `from __future__ import annotations`; `argparse`, `json`, `sys`, `datetime`, `typing`,
  plus `packaging.version` / `packaging.utils`.
- **Purity:** every function except the CLI shim is pure. No clock read, no filesystem, no
  network, no `subprocess` outside `main`'s helpers. The clock enters as a parameter.
- No `except Exception: pass` anywhere. Every caught exception either becomes a kept finding or
  an exit-2 error with the exception type and message in the text.

### 4.2 Types

```
class Advisory(NamedTuple):
    package: str        # as reported (display)
    key: str            # canonicalize_name(package) (matching)
    version: str        # as reported
    advisory_id: str    # as reported; "<unknown>" when unusable
    fix_versions: tuple[str, ...]   # display only (TD-D3)
    aliases: tuple[str, ...]        # display only (TD-D3)
    malformed: bool     # True when the record could not be fully parsed

class Exemption(NamedTuple):
    package: str            # PEP 503 canonical, lowercase
    advisory_id: str        # exact id as pip-audit reports it
    fixed_in: str           # PEP 440; the advisory's published fix version
    expires: datetime.date  # a date object, not a string (TD-D4)
    reason: str             # >= 40 chars; why this is not reachable here
    tracking_issue: int     # the issue that owns the renewal

class Suppressed(NamedTuple):
    advisory: Advisory
    exemption: Exemption

class Kept(NamedTuple):
    advisory: Advisory
    note: str | None        # None = no exemption applies at all;
                            # otherwise EXPIRED / PREMISE BROKEN / UNPARSEABLE VERSION text

class Decision(NamedTuple):
    kept: list[Kept]
    suppressed: list[Suppressed]
    roster: list[tuple[Exemption, str]]   # (record, status) for every record — §6.4
    raw_count: int          # records read from the audit, pre-dedup
    distinct_count: int     # after dedup (TD-VF-1)
```

### 4.3 The `packaging` dependency, declared

The module imports `packaging.version.Version` and `packaging.utils.canonicalize_name`.
`packaging` is already present in the venv as a transitive of `pip-audit`, but
`requirements.txt`'s own standing rule — set by the PyYAML comment in that file ("the gate must
not depend on that luck … Declare what we import", CPS#73/#74, HOS#48/#49) — requires
declaring it. Add `packaging>=23.0` with a comment pointing at this module.

Hand-rolling version comparison is rejected under CLAUDE.md's "Use the Code, Don't Roll It
Yourself": PEP 440 ordering has pre-releases, post-releases, epochs and local versions, and a
hand-rolled tuple compare that mis-orders `26.2` against `26.2.0` (an actual string pair from
TD-VF-1) would be a silent correctness hole inside a security control.

### 4.4 Functions

```
parse_audit(document: object) -> list[Advisory]
```
Takes the already-`json.loads`-ed audit document. Raises `AuditParseError` (a module-level
exception) when the document cannot be audited at all: not a mapping, or `dependencies` absent
or not a list. Per-entry handling:

- a `dependencies` entry that is not a mapping, **and carries anything**: emit one
  `Advisory(malformed=True, advisory_id="<unattributable>")` — kept, never suppressible;
- a mapping with no `vulns` or an empty `vulns`: ignored (117 of 117 deps go through this
  path on a clean run; being strict here would fail the gate on harmless shape drift);
- a mapping with `vulns` but a missing/non-string `name` or `version`: every vuln in it becomes
  `malformed=True` — kept, never suppressible;
- a `vulns` entry that is not a mapping, or whose `id` is missing/non-string/empty:
  `advisory_id="<unknown>"`, `malformed=True` — kept, never suppressible;
- `fix_versions`/`aliases` absent or not lists: coerced to `()`, **not** an error (display
  only, TD-D3).

**Deduplication** (TD-VF-1): after parsing, collapse advisories on
`(key, version, advisory_id)`, keeping the first occurrence and unioning `fix_versions` and
`aliases` for display. `raw_count` records the pre-dedup total, `distinct_count` the post. A
`malformed=True` advisory never participates in dedup (it has no reliable identity) and is
always kept individually.

```
validate_exemptions(rules: Iterable[Exemption]) -> list[str]
```
Returns a list of human-readable errors; empty means valid. Checks, per record:
`package` non-empty and already PEP 503-canonical (`canonicalize_name(p) == p`);
`advisory_id` non-empty; `fixed_in` parses as a PEP 440 `Version`; `expires` is a
`datetime.date` (and **not** a `datetime.datetime`); `reason` at least 40 characters;
`tracking_issue` a positive `int`. Across records: `(package, advisory_id)` must be unique.
A non-empty result is **exit 2** (TD-D6) — never "skip the bad record and carry on", because a
dropped record is an unexplained behaviour change in a control.

```
partition(advisories, rules, today) -> Decision
```
Pure. Applies §TD-D2's four conditions in order, producing for each advisory either a
`Suppressed` or a `Kept` with the note that explains the near-miss:

| Situation | Result | Note text |
|---|---|---|
| no record matches (name, id) | Kept | `None` |
| matches, `Version(installed)` unparseable | Kept | `UNPARSEABLE VERSION: …` |
| matches, `installed >= fixed_in` | Kept | `PREMISE BROKEN: …` (TD-D2) |
| matches, `today > expires` | Kept | `EXEMPTION EXPIRED …` (TD-D5) |
| all four hold | Suppressed | — |
| `advisory.malformed` | Kept | `UNATTRIBUTABLE: …` — matching is skipped entirely |

`roster` is built from **all** rules, each tagged `applied` / `not-needed (no matching
advisory reported)` / `expired` / `expiring in N day(s)`, so §6.4 can print the full list.

```
render(decision, today) -> tuple[list[str], int]
```
Pure. Returns the output lines and the exit status (0/1). Separated from the CLI so the exact
output text is unit-testable without capturing stdout. Ordering is fixed by §6.4.

### 4.5 Fail-closed matrix (exhaustive)

| Condition | Exit | Rationale |
|---|---|---|
| stdin is not valid JSON | **2** | nothing was audited; cannot report a pass |
| root is not a mapping | **2** | ditto |
| `dependencies` missing / not a list | **2** | ditto |
| `validate_exemptions` returns errors | **2** | the roster itself is broken; the gate cannot know what it is exempting |
| a dependency entry is malformed but carries vulns | 1 | kept as `UNATTRIBUTABLE`, never suppressed |
| a vuln entry has no usable `id` | 1 | kept as `<unknown>`, never suppressed |
| installed version unparseable by PEP 440 | 1 | kept; a version we cannot order cannot be bounded |
| a record's `fixed_in` <= installed | 1 | kept, `PREMISE BROKEN` |
| a record has expired | 1 | kept, `EXEMPTION EXPIRED` |
| every advisory suppressed | 0 | with the full roster + suppression list printed |
| no advisories at all | 0 | with the roster printed (`not-needed` for each) |

Exit 2 must also be reachable with a **non-zero** number of findings — i.e. an unreadable
roster fails even when the audit itself was clean. The status is about the gate's ability to
decide, not about the audit's result.

### 4.6 CLI shim

`main(argv)` with one subcommand, mirroring TD-VF-7:

```
security_scan_logic.py filter      # pip-audit JSON on stdin
```

Reads stdin, `json.loads`, calls `parse_audit`, `validate_exemptions`, `partition`, `render`;
prints the lines; returns the status. The clock is read exactly once, here. Parse and
validation failures print to **stderr** with the exception type and message (precedent:
`_cmd_filter`'s `GATE FAIL: could not parse detect-secrets output (…)`) and return 2.

`argparse`'s subcommand is `required=True`, so a bare invocation is a usage error rather than a
silent read of an empty stdin.

---

## 5. The exemption roster (C1's `SUPPRESSIONS`)

**Ten records across five packages** — one per (package, advisory), because §TD-D2 keys on the
advisory id and each advisory needs its own `fixed_in` and its own justification. `cryptography`
is **absent by ruling** and §9 TC-S7 pins its absence.

| # | package | advisory | fixed_in | expires | justification (the `reason` field must say at least this) |
|---|---|---|---|---|---|
| 1 | `anyio` | `CVE-2026-63374` | `4.14.2` | 2026-12-22 | IDNA-2003 hostname handling in `connect_tcp()`/`TLSStream.wrap()`. HOS opens no TLS connection through anyio: it is a transitive of `httpx`/`mcp`/`starlette`/`sse-starlette`, none of which HOS code imports (`grep -rn "import anyio\|import httpx" --include=*.py scripts/ bootstrap/ bin/` → no hits outside the venv). Reachable only if a bundled tool makes an outbound TLS call to an attacker-chosen IDN host. |
| 2 | `anyio` | `CVE-2026-64847` | `4.14.2` | 2026-12-22 | Undrained stderr pipe in process-pool workers. HOS does not use anyio's process pool; no HOS code imports anyio. |
| 3 | `anyio` | `CVE-2026-63349` | `4.14.2` | 2026-12-22 | Same reachability argument as #1/#2: transitive, unimported, no untrusted input path. |
| 4 | `black` | `PYSEC-2026-2121` | `26.3.1` | 2026-12-22 | Build/dev formatter, run by `lint_check` over **files already in the repository**, i.e. content that has passed the same review as the rest of the branch. Cannot be fixed by upgrade: `requirements.txt` pins `black>=24.0,<25.0` **deliberately** (#103 — a floating black reformats untouched code and reds the lint gate), and both fixes are in 26.x. Renewal requires the formatter-migration decision, not a version bump (RISK-3). |
| 5 | `black` | `PYSEC-2026-2120` | `26.3.0` | 2026-12-22 | As #4. |
| 6 | `click` | `PYSEC-2026-2132` | `8.3.3` | 2026-12-22 | CLI argument-parsing library, transitive of `black`/`mutmut`/`semgrep`/`uvicorn`. HOS code does not import click; the only argv reaching it is HOS's own gate invocations, not untrusted input. |
| 7 | `mcp` | `PYSEC-2026-3481` | `1.27.2` | 2026-12-22 | Model Context Protocol client/server library, present **only** as a transitive of `semgrep`. HOS runs semgrep as a local static analyser with no MCP server configured, so the vulnerable client/transport code is never entered. |
| 8 | `mcp` | `PYSEC-2026-3482` | `1.27.2` | 2026-12-22 | As #7. |
| 9 | `mcp` | `PYSEC-2026-3483` | `1.28.1` | 2026-12-22 | As #7. Note the distinct `fixed_in`. |
| 10 | `pip` | `PYSEC-2026-3721` | `26.2` | 2026-12-22 | The venv's own installer. `_create_venv` already runs `pip install --upgrade pip`, so a freshly built venv is on 26.2.1 and this record is inert there (TD-VF-2); it covers long-lived clones only. pip is invoked by HOS against `requirements.txt` files already in the repository. |

**Coder obligation:** re-run `pip-audit --format json` and confirm each `advisory_id` and
`fixed_in` against the tool's own output *and* the advisory text before writing the records.
Do not copy this table or the issue's table blindly — TD-VF-1 shows the issue's table already
drifted. If an advisory has disappeared or its id changed, **do not invent a record for it**:
omit it, and note the omission in the PR body.

`reason` strings must be written in full prose in the module (the table's "at least this" is a
floor, not the text). Each must answer: what is the vulnerability, how does the package get
here, and why is it not reachable with untrusted input in HOS?

---

## 6. C2 — `scripts/oversight/gates/security_scan.sh`

### 6.1 Scope of the change

**Only** the pip-audit branch (`=== pip-audit (dependency vulnerabilities) ===` to the end of
that `if`). The changeset parsing, the `INV-SELECTOR` case statement, the suspension check, the
bandit branch and the final summary block keep their current behaviour except where §6.3 says
otherwise. `hos_changeset_parse` / `hos_changeset_summary` / the `empty|all|unscoped|ok` arms
are untouched — #1759's grammar is not renegotiated here.

### 6.2 Tool resolution and the test seam

Mirror `secret_scan.sh:130-141` exactly:

```
PARSE_PY="${OVERSIGHT_PYTHON:-python3}"
AUDIT_FILTER="$GATES_DIR/../security_scan_logic.py"
# HOS_PIP_AUDIT_BIN overrides the resolution below — off by default, inert in
# the real pipeline, present only so a test can point this gate at a stub.
PIP_AUDIT=""   # $HOS_PIP_AUDIT_BIN, else $VENV_BIN/pip-audit, else command -v pip-audit
```

The `HOS_PIP_AUDIT_BIN` seam is the *binary* override already accepted for
`HOS_DETECT_SECRETS_BIN` under #1754's Ruling H. It is **not** a payload override: no
environment variable may supply the audit JSON directly, because that would be a one-variable
bypass of a security gate. A stub binary that prints a payload is the same trust surface as the
real binary and is how §9.3's shell-level tests inject synthetic audits.

### 6.3 Control flow

1. Resolve `PIP_AUDIT`; if empty, keep today's `SKIP:` message (unchanged).
2. Run `pip-audit --progress-spinner off --format json` under `with_timeout`/`run_with_retry`
   exactly as today, including the rc-0-or-1-plus-parseable-JSON success predicate (#672 — do
   not touch this; it is load-bearing and already correct).
3. On retry exhaustion: print the TD-D8 `NOT CHECKED` text and continue **without**
   incrementing `ERRORS` (behaviour unchanged, wording changed).
4. On success: `PYTHONSAFEPATH=1 "$PARSE_PY" "$AUDIT_FILTER" filter < "$PIP_AUDIT_TMP"`,
   capturing the status into `AUDIT_STATUS` (declared **outside** the branch, like
   `SCAN_STATUS` in `secret_scan.sh`, so the summary can distinguish the cases).
5. `AUDIT_STATUS != 0` → `ERRORS=$((ERRORS + 1))`.
6. **Delete both inline `python3 -c` snippets** (the `VULN_COUNT` counter and the finding
   printer) and both `|| echo "0"` fail-opens with them. The shell must contain no JSON parsing
   after this change.
7. Final summary: when `AUDIT_STATUS -eq 2`, the gate's closing line must say the audit could
   not be *read*, not that vulnerabilities were found — the `secret_scan.sh` summary block is
   the template:

```
GATE FAIL: the dependency audit could not be read — see the parse error above.
           Nothing was decided; this is a failure to check, not a clean result.
```

### 6.4 Output contract (AC-3)

The module prints, in this order, **always** — including on a passing run, and before any
pass/fail line (the #1754 ordering rule):

1. **The roster**, every record, one line each:

```
  Dependency-advisory exemptions in force (10 record(s), #1776 ruling 2026-09-23):
    anyio        [CVE-2026-63374]  until 2026-12-22  APPLIED       — <reason, first clause>
    black        [PYSEC-2026-2121] until 2026-12-22  APPLIED       — <reason, first clause>
    click        [PYSEC-2026-2132] until 2026-12-22  not needed (not reported in this environment)
    ...
```

Printing the whole roster, not just the applied subset, is a deliberate strengthening of
#1754's "print what was suppressed": TD-VF-2 shows most records will be *inert* on a fresh
venv, and an inert exemption that nobody can see is exactly the stale-suppression rot this
mechanism is supposed to avoid.

2. **Expiry warnings**, if any record expires within 14 days (TD-D5).
3. **The suppression detail**, per suppressed advisory — package, version, advisory id, fix
   version, expiry, tracking issue, and the full reason. This is the line that literally
   satisfies "which advisory, why, until when".
4. **Kept advisories**, each with its note when it has one (`EXEMPTION EXPIRED`,
   `PREMISE BROKEN`, `UNPARSEABLE VERSION`, `UNATTRIBUTABLE`), followed by
   `GATE FAIL: N dependency advisory(ies) not covered by an exemption`.
5. **The summary line**, one of:
   - `OK: no dependency advisories outside the exemption roster (N suppressed, M distinct advisories read from R raw record(s))`
   - `GATE FAIL: …` as above.

When an advisory for `cryptography` is kept, the kept line additionally carries the remedy, so
a stale venv explains itself rather than looking like a mystery (TD-D7's backstop):

```
    REMEDY: this venv predates the `cryptography>=50.0.0` floor. Run
            `bash scripts/oversight/ensure_venv.sh` to reconcile it, or
            `scripts/oversight/.venv/bin/pip install -r scripts/oversight/requirements.txt`.
```

---

## 7. C3/C4 — the `cryptography` bump and how an existing venv picks it up

### 7.1 `requirements.txt` (C3)

Two additions, each with a comment in the file's existing explain-yourself style:

```
# Not imported by HOS code — the App-token JWT is signed by openssl
# (bootstrap/get_app_token.sh), not by this package. The floor exists because the
# shared oversight venv must not sit on a cryptography with a live advisory
# (PYSEC-2026-3552 / CVE-2026-69247): the venv is the execution environment for
# every gate, validator and agent CLI. Human ruling on #1776, 2026-09-23 — this
# one is bumped for real rather than exempted.
cryptography>=50.0.0

# PEP 440 version ordering + PEP 503 name canonicalisation for
# security_scan_logic.py's exemption matching (#1776). Arrives transitively via
# pip-audit, but the gate must not depend on that luck — declare what we import
# (same rule as PyYAML above).
packaging>=23.0
```

**Floor, not pin.** `>=50.0.0` lets a fresh resolve take 50.0.1 (available today) or later. A
`==` pin would need a follow-up PR per patch release and would itself become a source of
always-red.

### 7.2 `ensure_venv.sh` reconcile (C4)

The contract, not the code:

- **Fingerprint.** After a successful create *or* a successful reconcile, write a marker file
  inside the venv (e.g. `$VENV/.hos-requirements-sha256`) containing a hash of
  `scripts/oversight/requirements.txt`'s bytes. It lives inside the venv so deleting the venv
  discards it, and so two clones cannot share one marker.
- **Trigger.** On every sourcing, after the existing stale-shebang and smoke-test checks pass,
  compare the marker against the current file hash. Equal, or venv freshly created → do
  nothing (the common path must add no measurable cost: one hash of a ~3 KB file).
- **Action on mismatch.** Run `"$VENV_BIN/pip" install --quiet -r requirements.txt`.
  **Without `--upgrade`.** This is the load-bearing constraint: bare `-r` installs or upgrades
  only what fails to satisfy a declared specifier, so `cryptography` 49 → 50 happens and
  `black` 24.10.0 stays put under its `<25.0` pin, and the unpinned transitives
  (`anyio`, `click`, `mcp`) are **not** floated. `--upgrade` would float everything and break
  #103's determinism guarantee outright — it must not appear.
- **Marker update.** Only after pip exits 0. A failed reconcile leaves the old marker, so the
  next invocation retries rather than recording a success that did not happen (the same
  "marker is a cache hint, not a trust anchor" rule the file already applies to the smoke-test
  marker).
- **Failure handling.** pip non-zero → `_evenv_err` with the same disk/network wording as
  `_create_venv`, and the same exit status behaviour as the existing install failures. A
  reconcile that cannot complete must not be silent.
- **Missing marker on an existing venv** (every venv in existence today) → treat as a mismatch
  and reconcile once. This is what actually delivers the bump to this clone.
- **Scope.** Hash **only** `scripts/oversight/requirements.txt`. Project requirements
  (`_install_project_requirements`) keep today's create-time-only behaviour, and
  `HOS_SKIP_PROJECT_REQUIREMENTS` is untouched — this repo has no root `requirements*.txt`
  (verified), and widening the trigger to branch-controlled files would make every branch able
  to trigger a pip install from `ensure_venv.sh`, which is a #1380 concern, not a #1776 one.
- **Output.** One line on the reconcile path (`requirements.txt changed — reconciling venv …`),
  nothing on the common path.

### 7.3 Verifying the bump (R1's "not a blind bump")

Landing evidence the PR body must carry, in this order:

1. `scripts/oversight/.venv/bin/pip show cryptography` → `Version: 50.0.x`, obtained **via**
   `bash scripts/oversight/ensure_venv.sh` (proving §7.2 works), not via a manual
   `pip install -U`.
2. `bash scripts/framework/run_tests_inner_loop.sh` green.
3. `bash scripts/oversight/run_gates.sh <the branch's changed files>` → `security_scan` passes
   (AC-1), with the roster visible in the output.
4. `bash scripts/oversight/smoke_test.sh` green (the shared venv still works for every other
   consumer).
5. `scripts/oversight/.venv/bin/pip check` clean (no dependency conflict introduced).

---

## 8. Protected surfaces

Checked against `scripts/framework/protected_surfaces.txt`:

| Path | Protected today | Action |
|---|---|---|
| `scripts/oversight/gates/security_scan.sh` | **yes** (`scripts/oversight/gates/**`) | none — the PR is human-gated because of it |
| `scripts/oversight/security_scan_logic.py` | **no** | **add it** (TD-D9) |
| `scripts/framework/protected_surfaces.txt` | **yes** (`scripts/framework/**`) | the addition is itself human-approved |
| `.github/CODEOWNERS` | **yes** (generated) | regenerate via `bash scripts/framework/regen_all.sh`; `--check` must be clean before the PR |
| `scripts/oversight/requirements.txt`, `ensure_venv.sh` | no | — |

**Why TD-D9.** Under the #1754 shape the gate shell is human-gated but the module beside it is
not — and in *this* module the unprotected half holds the exemption roster and its expiry
dates. Without the addition, an agent could add a package to `SUPPRESSIONS`, or push an expiry
date out by a year, in a PR that no human has to approve. That is precisely a control
loosening on the controls' own say-so, which the header of `protected_surfaces.txt` exists to
forbid. One line closes it.

**Noted, not acted on:** `scripts/oversight/secret_scan_logic.py` has the identical exposure
today. Out of scope here (it is #1754's surface, not #1776's), but it should be raised with the
architect as a sibling finding rather than left unsaid.

---

## 9. Test plan — `tests/oversight/test_security_scan_exemptions.py`

House style follows `tests/oversight/test_secret_scan_validator_artifact.py`: a module
docstring stating what is pinned, `load_module_from_path` from `tests/conftest.py`, hermetic
logic tests, and end-to-end gate tests that `pytest.skip` when the tool is absent.

Helper: `_audit(*entries)` builds a synthetic pip-audit document
(`{"dependencies": [{"name": …, "version": …, "vulns": [{"id": …, "fix_versions": [...],
"aliases": [...]}]}], "fixes": []}`) — the exact shape observed in TD-VF-1, including the
`fixes` key. **No test depends on the live network or on the real venv's contents**, except the
two explicitly-marked environment tests (TC-E1/TC-E2) and the one live gate run (TC-G1).

### 9.1 Matching and keying (AC-2 core)

| id | Test | Expectation |
|---|---|---|
| TC-S1 | A package **not** on the roster, vulnerable (`requests 2.0.0` / `CVE-2099-0001`) | kept; status 1. **This is the AC-2 proof.** |
| TC-S2 | Each of the ten roster records, at a version below its `fixed_in` | suppressed; status 0 |
| TC-S3 | A roster package at a version **≥ `fixed_in`**, advisory still reported | kept, note `PREMISE BROKEN`; status 1 |
| TC-S4 | A roster package, a **different** advisory id | kept; status 1 |
| TC-S5 | Name-canonicalisation: `ANYIO`, `any_io`, `any-io` reported for a roster advisory | canonical variants of the same name match; a genuinely different name does not |
| TC-S6 | Installed version unparseable (`"not-a-version"`) on a roster advisory | kept, note `UNPARSEABLE VERSION`; status 1 |
| TC-S7 | **`cryptography` is absent from `SUPPRESSIONS`**, asserted over the roster itself; and `cryptography 49.0.0 / PYSEC-2026-3552` is kept | kept; status 1. Pins ruling R1 against a future "just exempt it too". |
| TC-S8 | Roster uniqueness: no two records share `(package, advisory_id)` | asserted over `SUPPRESSIONS` |

### 9.2 Expiry (AC-3 "until when")

| id | Test | Expectation |
|---|---|---|
| TC-X1 | `today == expires` | suppressed (valid *through* the date) |
| TC-X2 | `today == expires + 1 day` | kept; note contains `EXEMPTION EXPIRED`, the date, and the tracking issue; status 1 |
| TC-X3 | `today == expires - 13 days` | suppressed **and** an `EXPIRING SOON` line is rendered |
| TC-X4 | `today == expires - 15 days` | suppressed, no warning line |
| TC-X5 | **No shipped record is already expired** — evaluated against the real clock | fails the day the time box lapses; the message names every lapsed record and the renewal path. This is the forcing function that stops the roster being renewed by silence. |
| TC-X6 | `validate_exemptions` rejects `expires` given as a `str`, and as a `datetime.datetime` | error list non-empty |

### 9.3 Fail-closed (AC-3 "never silent" / TD-D6)

| id | Test | Expectation |
|---|---|---|
| TC-F1 | stdin is not JSON | CLI exit **2**, message on stderr names the exception type |
| TC-F2 | root is a list / `dependencies` missing / `dependencies` not a list | exit **2** each |
| TC-F3 | A malformed roster (injected `rules=`, e.g. blank `reason`, non-canonical package, unparseable `fixed_in`, duplicate key) | `validate_exemptions` non-empty; the CLI path for the same condition exits **2** |
| TC-F4 | A dependency entry with `vulns` but no `name` | kept as `UNATTRIBUTABLE`, never suppressed, status 1 |
| TC-F5 | A vuln entry with no `id`, for a **roster package at a roster version** | kept — proves a malformed record cannot ride an exemption in |
| TC-F6 | A clean audit (`dependencies` present, zero vulns) **with** a broken roster | exit **2**, not 0 — the gate's ability to decide is what is being reported |
| TC-F7 | Suppression output is present on a **passing** run | roster + suppression lines appear with status 0 |

### 9.4 Parsing and reporting (TD-VF-1)

| id | Test | Expectation |
|---|---|---|
| TC-P1 | The same `(name, version, id)` twice in one `vulns` list | one advisory; `raw_count=2`, `distinct_count=1`; both counts in the summary line |
| TC-P2 | Same id, differing `fix_versions` (`["26.2"]` / `["26.2.0"]`) | deduped; both fix strings shown; **match unaffected** (TD-D3) |
| TC-P3 | A 117-dependency document with 3 vulnerable entries | only the 3 are considered; the 114 clean entries are silent |
| TC-P4 | The roster is printed in full even when nothing matches | every record appears with `not needed` |
| TC-P5 | The suppression line for each suppressed advisory contains the id, the reason and the expiry date | AC-3, asserted literally |

### 9.5 Gate-level (AC-1)

| id | Test | Expectation |
|---|---|---|
| TC-G1 | Run the real `security_scan.sh` against this repo's changed files, in the real venv | exit 0, roster visible. `pytest.skip` when `pip-audit` is absent **or** the run reports `NOT CHECKED` (offline) — a network-dependent assertion must not be a flaky red |
| TC-G2 | Run the gate with `HOS_PIP_AUDIT_BIN` pointing at a stub that prints a payload containing a **new** vulnerable package | gate exits 1 — AC-2 proven end-to-end through the shell, not only in the module |
| TC-G3 | Same seam, stub prints the roster's own advisories only | gate exits 0 and prints the suppression block |
| TC-G4 | Same seam, stub prints invalid JSON with rc 0 | gate exits 1 **and** the summary says the audit *could not be read* (the exit-2 → summary-text mapping of §6.3 step 7) |
| TC-G5 | `security_scan.sh --empty-changeset` | unchanged `NOT CHECKED` behaviour; pip-audit not run (#1759 regression guard) |

### 9.6 Environment (AC-4)

| id | Test | Expectation |
|---|---|---|
| TC-E1 | `requirements.txt` declares a `cryptography>=50.0.0` floor and a `packaging` floor | static text assertion; no venv needed |
| TC-E2 | The installed `cryptography` satisfies the declared floor | `pytest.skip` when the venv is absent; otherwise compares with `packaging.version` |
| TC-E3 | `black`'s `<25.0` pin is still present | guards against a "fix" that silently unpins black and re-breaks #103 |
| TC-E4 | `scripts/oversight/security_scan_logic.py` appears in `protected_surfaces.txt` | pins TD-D9 against a later removal |

### 9.7 Mutation-testing note

`mutmut` is in the venv and the logic here is exactly the kind a mutation run rewards (four
boolean conditions and a `<`/`<=` boundary). If the coder's budget allows, a targeted
`mutmut run` restricted to `security_scan_logic.py` is worth doing — in particular to confirm
TC-X1/TC-X2 pin the `today <= expires` boundary rather than merely the general shape. Not a
blocker.

---

## 10. Build order

| Slice | Content | Gate before moving on |
|---|---|---|
| **S1** | C3 (`requirements.txt`) + C4 (`ensure_venv.sh` reconcile) + TC-E1–TC-E3 | `ensure_venv.sh` upgrades this clone's `cryptography` to 50.x; `pip check` clean; `run_tests_inner_loop.sh` green (R1's verification pass, before any suppression exists) |
| **S2** | C1 (`security_scan_logic.py`) with the roster, plus §9.1–§9.4 | module tests green; `flake8`/`black`/`mypy` clean |
| **S3** | C2 (gate rewiring) plus §9.5 | `run_gates.sh <changed files>` → `security_scan` passes (AC-1) |
| **S4** | C5/C6 (protected surface + CODEOWNERS) plus TC-E4 | `scripts/framework/regen_all.sh --check` clean |
| **S5** | C8 (`DECISIONS.md`) + follow-up issues (§10.5) | — |

S1 lands the ruling's part 1 on its own, so if the exemption mechanism needs another review
round the `cryptography` bump is already verified independently.

### 10.5 Follow-up issues the coder must open

1. **Renewal owner** — "Revisit the `security_scan` dependency exemptions before 2026-12-22
   (#1776)". Every roster record's `tracking_issue` points at it. It must list the five
   packages, name `black` as the one requiring a formatter decision rather than a bump
   (RISK-3), and say plainly that extending a date without a fresh human decision is not an
   option.
2. **pip-audit fail-open** — TD-D8's residual: pip-audit failing to complete currently passes
   the gate. Needs its own ruling (offline local runs vs. a blocking network dependency).
3. **`secret_scan_logic.py` protected-surface parity** — §8's sibling finding.
4. *(architect's call, not the coder's)* re-wiring `security_scan` into `oversight-gates.yml`,
   now unblocked for the first time (TD-VF-3, `DECISIONS.md:787`).

---

## 11. Startup-gap analysis

**Was this a startup-artifact gap?** No — and the evidence is explicit.
`DECISIONS.md:787` (2026-09-10/11, #1216) records the deliberate decision **not** to wire
`security_scan` into CI precisely *because* it lands red on pre-existing dependency findings,
and names the two candidate remedies. The always-red local behaviour is therefore recorded,
accepted technical debt now being paid, not a contract the original design failed to specify.

**Affected sign-offs.** The exemption mechanism is new; it changes no contract that prior code
was reviewed against. Every prior sign-off stands. The one behaviour *change* to existing
reviewed code is the removal of the two `|| echo "0"` fail-opens in `security_scan.sh`
(TD-D6) — that strictly tightens the gate, so no previously-approved code becomes
under-audited by it. No approval is orphaned by this design.

---

## 12. Residual risks flagged for decision

**RISK-1 — the ruling's `cryptography` premise does not match the code (§TD-VF-6).**
The JWT is signed by `openssl`; `cryptography` is an unimported orphan with an empty
`Required-by`. The ruled action (bump to ≥50.0.0) is implemented **unchanged**; the bump is
simply lower-risk than assumed, since it cannot break a dependent. Raised so the correction is
on the record rather than buried, and so the human can decide *separately and later* whether an
unused package belongs in the venv at all. **No action requested in this slice.**

**RISK-2 — expiry date and cliff shape.** All ten records expire on **2026-12-22** (90 days
from the ruling). A single cliff means one renewal review rather than five interruptions, and
the 14-day `EXPIRING SOON` warning gives a runway. The cost is that if renewal is missed, five
packages red the gate at once. Staggering is supported by the schema (per-record dates) and
would trade one outage for several smaller ones. **Architect/human to confirm the date and the
shape.**

**RISK-3 — `black` cannot be renewed by upgrading.** Its fixes are in 26.x; `requirements.txt`
pins `<25.0` deliberately (#103). In December the options are: migrate the formatter (a
repo-wide reformat, its own PR and its own risk), make the exemption permanent with a
standing justification, or drop `black` from the gate's scope. None is decidable here.
**Named now so December is a decision, not a surprise.**

---

## 13. Out of scope (with reasons)

| Excluded | Why |
|---|---|
| The **bandit** half of `security_scan.sh` (two inline `python3 -c` snippets) | Same v0.7.4 "logic in Python" argument applies, but bandit is clean and not the failure under review. Folding it in doubles the diff on a protected surface for no AC. Worth a follow-up; not this PR. |
| Wiring `security_scan` into CI | TD-VF-3. Newly *possible* once this lands, but it is a workflow change with its own blast radius and needs the architect (§10.5 item 4). |
| Making pip-audit's non-completion blocking | TD-D8. Trades one always-red for another; needs a ruling. |
| A committed audit **baseline** diffed per PR (`DECISIONS.md:787`'s second remedy) | A second suppression mechanism, which R2 explicitly forbids. |
| Bumping `anyio`/`click`/`mcp`/`pip` | Ruled against: R2 exempts them precisely to avoid blind bumps in the shared venv. The reconcile in §7.2 deliberately does not float them. |
| Removing `cryptography` from the venv | Would be re-litigating R1 (see RISK-1). |
| `secret_scan_logic.py`'s protected-surface gap | #1754's surface; noted in §8, filed in §10.5. |
| Any change to `run_gates.sh`, `lib/changeset.sh`, or the argument grammar | #1759 settled those; nothing here needs them. |

---

## 14. Architect review requested

Specific points on which I want a verdict rather than a nod:

1. **TD-D2's keying rule** — I deviated from the `(package, exact version, advisory)` triple
   the issue framing suggested, on the TD-VF-2 evidence that four of five exempted packages are
   unpinned transitives. Is the closed `fixed_in` upper bound accepted as "narrow enough"?
2. **TD-D7 / §7.2, the venv reconcile** — this is new machinery in a file every gate sources.
   Is a requirements-fingerprint reconcile the right mechanism, and is hashing *only*
   `scripts/oversight/requirements.txt` the right boundary?
3. **TD-D9 / §8** — adding the logic module to the protected-surface list, and the sibling
   finding about `secret_scan_logic.py`.
4. **RISK-2** — the single 2026-12-22 cliff versus staggered expiries.
5. **§13's first row** — leaving the bandit half in shell for now.
