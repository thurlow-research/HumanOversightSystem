# Technical Design — Installer and Consumer Compatibility (v0.4.0)

**Status:** draft — requesting architect review (iteration 1)
**Source spec:** `docs/specs/SPEC-installer-upgrade.md`
**Issues:** #238, #286, #287, #303 (Findings 4 and 5)
**Depends on:** `bootstrap/hos_install.sh`, `scripts/framework/install.sh`,
  `scripts/oversight/suspension_manager.py`,
  `scripts/oversight/gates/check_suspension.sh`,
  `scripts/oversight/validators/regions.py`, `scripts/framework/cut_release.sh`
**Written by:** technical-design · 2026-06-16

---

## HOS self-flag (this document)

```
RISK: MEDIUM
CONFIDENCE: MEDIUM
BLAST RADIUS: installer upgrade path (every consumer upgrade), CORE region
  content shipped to consumers (§2 strips lines), pack injection text (§3),
  gate-suspension parsing (§4/§5 — safety-relevant: a mis-parsed suspension
  silently runs or skips a gate).
```

Change classification: **structural** for §1 (adds a hard-stop that can abort an
upgrade, and a new content-currency gate that can refuse to record `.hos-release`)
and **structural** for §2 (the installer now *mutates* CORE region content on the
way to the consumer — CORE is HOS-owned and previously copied byte-exact). §3 is
**additive** (new substitution pass scoped to PACK). §4 is **additive** (new
`--check` subcommand). §5 is **clarifying/additive** (parser unification +
regression test).

### ## Human Review Required

§1 and §2 are structural. §1 can **block** a consumer upgrade (hard-stop on
version-skip; hard-stop on content-currency mismatch). §2 changes the long-held
invariant that CORE regions ship byte-exact to consumers — the installer will now
*remove lines* from CORE before writing. Both warrant human/architect sign-off
before the contract reaches the coder.

The load-bearing open question is **the interaction between §2 (strip CORE lines)
and §1 REQ-U-05 (content-currency SHA256 of CORE regions)**: if the installer
strips lines from a CORE region, the installed bytes no longer match the release's
CORE bytes, so a naive SHA check would *always* fail. The hashing boundary must be
defined so these two features compose. See OQ-1 — this blocks coding both §1 and §2.

---

## 0. Path corrections (the spec cites a wrong path — confirm before coding)

The task brief and SPEC §4/§5 reference
`scripts/oversight/validators/suspension_manager.py`. **The file actually lives at
`scripts/oversight/suspension_manager.py`** (validators/ holds the risk scorers;
`suspension_manager.py` is one level up). All §4/§5 work targets
`scripts/oversight/suspension_manager.py`. The test lives at
`tests/oversight/test_suspension_manager.py`. The gate helper is
`scripts/oversight/gates/check_suspension.sh`. These are the authoritative paths
for this design.

The transition-gate suite invocation in REQ-C-03 cites
`python scripts/oversight/suspension_manager.py --check` — correct path, use it.

---

## §1 — Cumulative upgrade on version-skip (#238)

### Component map

| Component | File | Change |
|---|---|---|
| Version-skip detection | `bootstrap/hos_install.sh` | New block after `.hos-release` read, before the agent install flow: fetch release list, compute adjacency, hard-stop or set `--full` mode |
| `--full` flag | `bootstrap/hos_install.sh` arg parser | New flag `--full` (bypasses adjacency check; preserves PROJECT) |
| Content-currency check | `bootstrap/hos_install.sh` (new fn) + new helper | After the agent flow, before the success message: hash installed CORE/PACK regions vs `SHA256SUMS` |
| SHA256SUMS generation | `scripts/framework/cut_release.sh` | Generate `SHA256SUMS` from the release's agent files; upload as a release asset |
| Region hashing | `scripts/oversight/validators/regions.py` | New `region-sha` is already present (see compose/region_sha CLI, regions.py header) — reuse it for canonical per-region hashing |
| Upgrade docs | `docs/UPGRADE-PR-REVIEW-CHECKLIST.md` | Add version-skip / `--full` section (REQ-U-07) |

### Where in the install flow

`bootstrap/hos_install.sh` currently: parse args → resolve `TARGET_REPO` →
placeholder setup (line ~531) → pack resolution (line ~599) → layered agent
install (line ~707 onward) → manifest + `.hos-release` write → success.

Insert:
1. **Version-skip gate** immediately after `TARGET_REPO` is resolved and
   `.hos-release` is readable, *before* placeholder setup. Rationale: hard-stop
   should fire before any file is touched.
2. **Content-currency check** after the layered agent install completes and the
   composed bytes are on disk, *before* writing `.hos-release` and the success
   message (REQ-U-05: must not record a `.hos-release` tag that does not match
   installed content).

### REQ-U-01 — installed-version detection

```bash
INSTALLED_TAG=""
[[ -f "${TARGET_REPO}/.hos-release" ]] && INSTALLED_TAG="$(tr -d '[:space:]' < "${TARGET_REPO}/.hos-release")"
# absent .hos-release ⇒ fresh install ⇒ skip the version-skip gate entirely
```

Fresh install (no `.hos-release`) → no prior-version assumption → skip §1's
adjacency gate (REQ-U-01). Content-currency (REQ-U-05) still runs on fresh
installs (it validates the *target* content regardless of prior version).

### REQ-U-02 — version-skip detection

```bash
# Sorted release tag list (newest-first) from the HOS releases API.
# Repo: thurlow-research/HumanOversightSystem  (confirm slug — OQ-2)
RELEASES_JSON="$(gh api repos/thurlow-research/HumanOversightSystem/releases \
  --jq '[.[] | select(.draft==false) | .tag_name]' 2>/dev/null)" || RELEASES_JSON=""
```

- **Releases API unavailable AND `.hos-release` present** → hard-stop
  (REQ-U-02): print `"cannot verify upgrade sequence — network required"` and
  exit non-zero. Do not proceed silently (AC-U-07).
- **Adjacency test:** `TARGET_TAG` is the tag being installed (`RELEASE_REF` if
  set, else the latest release tag). Find the index of `INSTALLED_TAG` and
  `TARGET_TAG` in the sorted list. The upgrade is **sequential** iff
  `INSTALLED_TAG` is the immediately-prior release to `TARGET_TAG` (index of
  installed == index of target + 1 in newest-first order, with no non-draft
  release between them). Otherwise it is a **version-skip**.
- Tag ordering uses the GitHub API's published order (newest-first) — the design
  does **not** re-implement semver sorting; it trusts the release list order and
  defines "skipped" as the set of tags strictly between target and installed in
  that list. **OQ-3:** confirm GitHub returns releases in published-date order
  reliably, or whether the installer must semver-sort defensively.

### REQ-U-03 — hard-stop message (exact)

When version-skip is detected and `--full` is **not** passed, emit verbatim
(substituting the bracketed values) and `exit 1`:

```
ERROR: version-skip detected.
  Installed: <installed-version>
  Target:    <target-version>
  Skipped:   <comma-separated skipped versions>

  A non-sequential upgrade risks a content-incomplete install.
  Supported paths:
    (a) Re-run with --full to install <target-version> wholesale
        (overwrites all CORE and PACK regions; PROJECT regions are preserved).
    (b) Apply each intermediate version in sequence:
        <one install command line per intermediate version, oldest first>

  Run with --full to proceed if you understand the implications.
```

The intermediate-version command lines (path b) are generated from the skipped
set, one per line, each of the form:

```
        ./bootstrap/hos_install.sh --release <version> <TARGET_REPO>
```

(oldest skipped version first, ending at `<target-version>`).

### REQ-U-03 — `--full` flag semantics

Add to the arg parser (alongside `--squash`, `--prune`):

```bash
FULL=false   # --full: bypass the version-skip adjacency hard-stop (#238)
...
--full)  FULL=true; shift ;;
```

`--full` changes exactly one thing in the flow: it **skips the adjacency
hard-stop** (REQ-U-02/03). It does **not** change the region-merge behavior —
the existing three-way merge already takes CORE and PACK from HOS and preserves
PROJECT (the installer header documents this). So a `--full` install of the
target = the normal install, minus the adjacency check. The content-currency
check (REQ-U-05) still runs and records `.hos-release` only on success.

Boundary: `--full` does **not** apply intermediate-release deltas (REQ-U-03) —
the HOS install is already wholesale-from-target (it does not diff against the
prior release; it composes from the target release's regions). So "wholesale" is
the existing behavior; `--full` only removes the safety stop. Confirm OQ-4: does
any part of the current installer actually compute a delta against the prior
release, or is every install already wholesale? If already wholesale, `--full`
is purely "skip the stop" and the spec's framing ("install wholesale") is
automatically satisfied.

### REQ-U-05 / REQ-U-06 — content-currency check + SHA256SUMS

**SHA256SUMS format (REQ-U-06):**

```
<sha256hex>  <agent-filename>:<region-name>
```

One line per CORE and PACK region of every shipped agent file. Example:

```
a3f1...  security-reviewer.md:CORE
b8c2...  security-reviewer.md:PACK:django
```

PROJECT regions are **excluded** (REQ-U-05 / AC-U-06).

**Canonical region serialization (the load-bearing definition — OQ-1/OQ-5).**
The hash must be over a *canonical* byte serialization of the region body, not
the raw file bytes (the spec's Implementation Notes flag this). `regions.py`
already defines body normalization (`_normalize_body`, used by `region_sha`) and
exposes a `region-sha` CLI. **Reuse `regions.py region_sha` as the single
canonicalization+hash function** for BOTH:
- `cut_release.sh` when generating `SHA256SUMS` (hash each region of each source
  agent file), and
- the installer's content-currency check (hash each region of each *installed*
  agent file).

Using one function on both ends guarantees the byte-for-byte agreement the spec
requires. The coder must not write a second hashing path.

**Generation (cut_release.sh, REQ-U-06):** after validation passes and before
tagging, for each agent in `scripts/framework/consumer_agents.txt`, for each
CORE/PACK region, run `regions.py region-sha <file> --region <id>` and write the
`<hash>  <agent>:<region>` line to a `SHA256SUMS` file. Upload `SHA256SUMS` as a
release asset (same mechanism `cut_release.sh` uses for the bootstrap scripts).

**Download location (REQ-U-05):** the installer downloads the target release's
`SHA256SUMS` to a temp path
(`"${_AGENT_STAGE}/SHA256SUMS"` or a fresh `mktemp`), via the release-asset URL
`https://github.com/<repo>/releases/download/<target-tag>/SHA256SUMS` (the same
well-known asset location `cut_release.sh` documents). If the asset is missing
for the target release → **OQ-6:** hard-stop, or warn-and-skip? The spec says
the check is a hard-stop on *mismatch*; it does not say what to do when
`SHA256SUMS` is absent (e.g. an older release predating this feature). Design's
provisional choice: **warn-and-skip** when the asset is absent (backward
compatibility with pre-feature releases), **hard-stop** on a present-but-
mismatching manifest. Architect to confirm.

**Check (REQ-U-05):** after the agent install writes composed bytes, for each
line in `SHA256SUMS`, recompute `regions.py region-sha` on the installed file's
named region and compare. Any mismatch → print which `agent:region` mismatched
and `exit 1` **before** `.hos-release` is written (AC-U-05).

> **§1↔§2 interaction (OQ-1, blocking).** §2 strips internal-path lines from
> CORE regions on install. If `SHA256SUMS` is computed over the *unstripped*
> source CORE region but the installed CORE region is *stripped*, every CORE hash
> mismatches. Resolution options for the architect:
>   (a) Compute `SHA256SUMS` over the **post-strip** CORE region (the
>       cut_release.sh strip and the installer strip must be the identical
>       function — see §2 — so both ends hash the stripped form). Cleanest if the
>       strip is deterministic and shared.
>   (b) Exclude CORE from content-currency and hash **PACK only** (weaker — loses
>       AC-U-05's CORE-corruption detection).
>   (c) Hash CORE pre-strip and run the strip as a *post-verification* step
>       (verify currency against source, then strip) — but then the installed
>       bytes never match the recorded hash, defeating REQ-U-05's intent.
> Design recommends **(a)**: make the strip a pure function shared by
> cut_release.sh and the installer, and hash the stripped result. This requires
> cut_release.sh to run the §2 strip before hashing. **This is the single most
> important architect decision in this document.**

### Acceptance-criteria trace (§1)

AC-U-01 → hard-stop on skip. AC-U-02 → `--full` installs + records tag.
AC-U-03 → sequential proceeds. AC-U-04 → currency passes post-`--full`
(depends on OQ-1 resolution). AC-U-05 → corrupted CORE caught pre-`.hos-release`.
AC-U-06 → PROJECT excluded. AC-U-07 → network-required hard-stop.

---

## §2 — Post-install path cleanup (#286)

### Component map

| Component | File | Change |
|---|---|---|
| Strip-list registry | `scripts/framework/installer-internal-paths.txt` (new) | New file, one prefix per line |
| Strip function | new `scripts/framework/strip_internal_paths.sh` (companion script) | Pure, idempotent strip of CORE-region lines |
| Installer hook | `bootstrap/hos_install.sh` | Call the strip after composing each agent's bytes, before writing to disk (Phase B) |
| Release-cut hook | `scripts/framework/cut_release.sh` | Run the same strip before hashing (per §1 OQ-1 option (a)) |

### REQ-P-01 — internal-path registry

New file `scripts/framework/installer-internal-paths.txt`, default content:

```
research/findings/
docs/SETUP
docs/CUSTOMIZATION
packs/
```

One prefix per line. Blank lines and `#`-comment lines ignored. A CORE-region
line is internal iff it **contains** any listed string as a substring (REQ-P-01:
"contains any listed prefix as a substring" — note this is substring-contains,
not line-start-anchored; the task brief's "start with or contain" is satisfied by
substring-contains).

### REQ-P-02/P-03 — strip behavior, CORE-region scope

**CORE-region detection.** A line is in a CORE region iff it lies between
`<!-- HOS:CORE:START -->` and `<!-- HOS:CORE:END -->` (the canonical markers
regions.py emits). The strip must track region state line-by-line and only strip
inside CORE; PACK and PROJECT lines pass through unchanged (REQ-P-03 / AC-P-03).

**Implementation approach (REQ-P-02).** Use a **Python or awk state machine**,
not a single `sed` (sed cannot cleanly do "only between markers" + "collapse
adjacent blanks" + idempotency in one expression). Recommended:
`strip_internal_paths.sh` is a thin bash wrapper around an inline `python3`
(stdlib only, matching `suspension_manager.py`'s no-venv convention) or an awk
program. The function:

```
strip_internal_paths(file, prefixes_file) -> rewrites file in place:
  region = OUTSIDE
  for line in file:
    update region on CORE START/END markers (markers themselves never stripped)
    if region == CORE and line contains any prefix:  drop line
    else: keep line
  collapse runs of >1 consecutive blank line to a single blank line  (REQ-P-02)
```

> Boundary: marker lines (`<!-- HOS:CORE:START/END -->`) are never candidates for
> stripping even if a prefix somehow matched — region transitions are evaluated
> before the contains-test, and markers are kept unconditionally.

**Idempotency (REQ-P-04 / AC-P-06).** Because the strip removes lines and then
collapses blanks, a second pass finds no internal-path lines and no >1 blank runs
→ identical output. The coder must add a test asserting `strip(strip(x)) ==
strip(x)`.

**Blank-line collapse scope.** Collapse applies across the whole file output
after stripping (the spec says "adjacent blank lines left by removals"); scoping
collapse to CORE-only is acceptable and safer (PACK/PROJECT untouched). Design
chooses **CORE-region-scoped collapse** to honor REQ-P-03's "PACK and PROJECT
regions are not modified." **OQ-7:** confirm collapse is CORE-scoped (a removal
at the CORE/PACK boundary could leave a blank adjacent to a PACK region — that
blank stays, as it is outside CORE).

### REQ-P-05 — install-log line

After stripping each agent file, if `N > 0` lines were removed:

```
[path-cleanup] <agent-filename>: removed <N> internal-path line(s)
```

Informational; does not affect exit code.

### REQ-P-06 — where the strip runs in the installer

The strip runs in `hos_install.sh` Phase B, **after** `regions.py compose`
produces the agent's composed bytes and **before** those bytes are written to
`$dst`. This keeps the strip on every fresh install and every upgrade
(sequential or `--full`), and never touches PROJECT (REQ-P-06). It runs against
the composed output, so the CORE markers are present for region detection.

> Per §1 OQ-1 option (a): the **same** strip function must also run in
> `cut_release.sh` before `SHA256SUMS` hashing, so the recorded CORE hash matches
> the stripped installed CORE. This makes `strip_internal_paths.sh` a shared
> primitive, not installer-only.

### Acceptance-criteria trace (§2)

AC-P-01 → no internal-path lines in CORE post-install. AC-P-02 → three lines
removed, blanks collapsed. AC-P-03 → PACK/PROJECT untouched. AC-P-04 →
`[path-cleanup]` log lines. AC-P-05 → new prefix strips on re-run. AC-P-06 →
idempotent.

---

## §3 — Pack placeholder substitution (#287)

### Component map

| Component | File | Change |
|---|---|---|
| Token substitution | `bootstrap/hos_install.sh` inject-pack block (line ~815) | After `regions.py inject-pack`, substitute `{{TOKEN}}` in the PACK region only |
| config.sh keys | `scripts/framework/install.sh` config generator | Add four keys with comments (REQ-S-04) |
| Pack source | `packs/<name>/*.md` | Pack author tokenizes example paths (REQ-S-03 — not installer work) |

### Token convention vs. the existing `{NAME}` mechanism (must not collide)

HOS already has a placeholder engine: `scripts/framework/placeholders.manifest`
declares single-brace `{NAME}` tokens substituted from `config.sh` over the
**staged template before regions.py composes** (the D6 boundary; see
`hos_install.sh` lines 531–597). §3's `{{TOKEN}}` is a **separate, double-brace**
convention applied **after** `inject-pack`, scoped to PACK only. The double-brace
syntax is deliberately distinct so the existing single-brace engine never touches
these tokens and vice versa. **Do not route the four `{{...}}` tokens through
placeholders.manifest** — they have different timing (post-inject, PACK-scoped)
and different syntax. OQ-8 records this so the architect confirms the two engines
stay separate.

### REQ-S-01 — substitution on inject, PACK-scoped

The four tokens and their `config.sh` keys:

| Token | config.sh key |
|---|---|
| `{{PROJECT_ROOT}}` | `PROJECT_ROOT` |
| `{{PROJECT_SETTINGS_MODULE}}` | `PROJECT_SETTINGS_MODULE` |
| `{{PROJECT_TESTS_DIR}}` | `PROJECT_TESTS_DIR` |
| `{{PROJECT_PACKAGE}}` | `PROJECT_PACKAGE` |

**Scoping to PACK only.** Two viable approaches; design selects (b):

(a) Substitute on the **pack body file** (`$_body`) *before* `inject-pack` reads
    it. Clean scoping (the body is pure PACK text), but mutates a temp copy of
    the source body. Requires staging `$_body` to a temp file first.

(b) Substitute on the composed agent file *after* `inject-pack`, but **only
    within the `PACK:<name>` region**, using the same marker-tracking state
    machine as §2. This guarantees CORE/PROJECT are untouched (REQ-S-01) even
    though they are present in the file.

**Design selects (a):** substitute the **pack body before injection**. Rationale:
the body file is 100% PACK content (no CORE/PROJECT markers to worry about), so
"PACK-only" is automatic and there is no risk of touching CORE/PROJECT. The
installer already stages bodies; add a substitution step on the staged body copy.

Implementation in the inject-pack loop (hos_install.sh ~line 815):

```bash
for _pk in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
  _body="$HOS_SOURCE/packs/$_pk/${agent}.md"
  [[ -f "$_body" ]] || continue
  # NEW: stage + token-substitute the body before injection (PACK-scoped by construction)
  _body_sub="$_AGENT_STAGE/${agent}.${_pk}.body.md"
  cp "$_body" "$_body_sub"
  _subst_pack_tokens "$_body_sub" "$agent"      # new helper, see below
  if ! python3 "$_REGIONS_PY" inject-pack "$_stage" \
        --name "$_pk" --body-file "$_body_sub" --in-place 2>"$_inj_err"; then
    ...
  fi
done
```

**`_subst_pack_tokens` (new bash helper).** Reads the four keys from `config.sh`
(reuse the existing config-read pattern in hos_install.sh / the perl approach
already used for `{NAME}`), then for each token whose value is non-empty:

```bash
# value already read into $val for token $tok (e.g. tok="PROJECT_ROOT")
perl -i -pe "s/\\{\\{${tok}\\}\\}/${val_escaped}/g" "$_body_sub"
```

Use `perl -i` (already used elsewhere in the installer) rather than `sed -i`
(BSD/GNU `sed -i` portability differs; the installer standardizes on perl for
in-place edits). `val_escaped` must escape `/` and `&` for the substitution
RHS — prefer building the perl program with the value as `$ENV{}` to avoid
injection:

```bash
val="$VALUE" tok="$TOK" perl -i -pe 's/\{\{\Q$ENV{tok}\E\}\}/$ENV{val}/g' "$_body_sub"
```

(`\Q...\E` quotes the token; `$ENV{val}` avoids interpolating the value into the
regex/program text — safer than string-building the perl source.)

### REQ-S-02 — missing-key behavior

For each token whose `config.sh` key is **absent or empty**: leave the literal
`{{TOKEN}}` in the body and emit exactly:

```
[pack-substitution] WARNING: token {{PROJECT_SETTINGS_MODULE}} has no value in config.sh — left literal in <agent-filename>
```

The install **must not fail** on a missing token (AC-S-02). The `\Q$ENV{tok}\E`
loop simply does no replacement when `val` is empty — but to satisfy the WARNING
requirement, the helper must explicitly check emptiness and emit the warning
rather than silently no-op.

### REQ-S-05 — confirmation log

If all tokens present in the body were substituted (none left literal):

```
[pack-substitution] <agent-filename>: substituted <N> token(s)
```

`<N>` counts distinct token *occurrences* substituted. If any token was left
literal, the WARNING line(s) are the log entry for that agent (no separate
confirmation line).

### REQ-S-04 — config.sh template keys

`scripts/framework/install.sh` (the config.sh generator) must emit the four keys
with empty-string defaults and explanatory comments, even when no pack is
installed (AC-S-05):

```bash
# Pack placeholder substitution (#287) — values substituted into PACK regions of
# .claude/agents/*.md when a pack is injected. Leave empty if not using a pack.
PROJECT_ROOT=""              # Absolute path to project root, e.g. /app
PROJECT_SETTINGS_MODULE=""   # Settings module path, e.g. parkshare/settings
PROJECT_TESTS_DIR=""         # Tests dir relative to PROJECT_ROOT, e.g. tests
PROJECT_PACKAGE=""           # Top-level package name, e.g. parkshare
```

### REQ-S-03 — pack source tokenization (not installer work — note for pack author)

The django pack source (`packs/django/*.md`) must use tokens, e.g.
`{{PROJECT_SETTINGS_MODULE}}/base.py`, `{{PROJECT_TESTS_DIR}}/factories.py`.
This is pack-author work, out of installer scope, but called out so the
substitution has something to act on. AC-S-01 depends on the pack being
tokenized. **OQ-9:** confirm whether tokenizing the django pack is in this
build step's scope or a separate pack-author task.

### Acceptance-criteria trace (§3)

AC-S-01 → token → value in PACK (depends on OQ-9 pack tokenization).
AC-S-02 → missing key → literal + WARNING, no fail. AC-S-03/04 → CORE/PROJECT
untouched (body-only substitution by construction). AC-S-05 → config.sh keys.
AC-S-06 → re-run substitutes corrected key.

---

## §4 — Suspension control-line / table-row consistency (`--check`, #303 Finding 4)

### Component map

| Component | File | Change |
|---|---|---|
| `--check` consistency sub-check | `scripts/oversight/suspension_manager.py` | Extend the existing `--check` to also parse the doc table and compute the symmetric difference |
| Table parser | `suspension_manager.py` | New `parse_table_gates(text) -> set[str]` |
| Transition gate hook | `scripts/framework/run_tests_inner_loop.sh` / the transition gate suite (OQ-10) | Invoke `--check`, treat non-zero as gate failure |

### Important: `--check` already exists and does something else

The current `--check` (suspension_manager.py lines 214–222) runs each
auto-checkable gate script and records pass/fail history. The spec REQ-C-01
wants `--check` to *also* do consistency validation. **Design decision:** add the
consistency check as an **additional** behavior of `--check` (it runs both: the
existing gate-pass recording AND the new consistency check), with the
consistency result driving the **exit code** (REQ-C-02: non-zero on mismatch).
The existing gate-pass recording does not currently set a failing exit code, so
adding a consistency-driven non-zero exit is a behavior change to `--check`'s
exit semantics. **OQ-11:** confirm `--check` should now exit non-zero on
consistency mismatch (today it returns 0 unconditionally) — this could affect any
existing caller of `--check`. Alternative: a dedicated `--check-consistency`
subcommand. Design provisionally extends `--check` per the spec's literal wording.

### REQ-C-01 — algorithm

```
control_gates  = { s.gate for s in parse_suspensions(text) }          # existing parser
table_gates    = parse_table_gates(text)                              # new
orphan_control = control_gates - table_gates   # control line, no table row
orphan_table   = table_gates - control_gates   # table row, no control line
mismatches     = orphan_control ∪ orphan_table
```

**`parse_table_gates(text)` — new function.** The doc table is the
"Currently suspended" documentation, distinct from the `## Re-enable log` table.
Parse markdown table rows whose first cell is a gate name. To avoid matching the
Re-enable log and the header/separator rows:
- Only consider lines that are table rows (`^\s*\|.*\|\s*$`).
- Skip the header row and the `|---|---|` separator.
- Skip rows under the `## Re-enable log` heading (track section state).
- The gate name is the first cell, trimmed; skip placeholder cells like
  `*(none yet)*`.

**OQ-12:** `gate-suspension.template.md` (the shipped template) does **not**
currently contain a "Currently suspended" *table* — it has `SUSPENDED:` control
lines and a separate "Re-enable log" table. The spec's §4 "documentation table"
presupposes a per-suspension doc table that may not exist in the current format.
Two readings: (i) the doc table the spec means is a new structure consumers must
add; or (ii) it refers to an existing convention in a real consumer's
`gate-suspension.md` not reflected in the template. The architect must confirm
which table `parse_table_gates` targets and whether
`gate-suspension.template.md` needs a "Currently suspended" table added. This
blocks coding §4.

### REQ-C-02 — output format

Per orphan:

```
SUSPENSION-MISMATCH: <gate-name>
  control-line: present | absent
  table-row:    present | absent
  file: contract/gate-suspension.md
```

Summary line:

```
suspension-consistency: FAIL — <N> mismatch(es) found
```

or, when clean:

```
suspension-consistency: OK
```

Exit non-zero when any mismatch (REQ-C-02).

### REQ-C-03/04/05 — pipeline placement and mode behavior

- REQ-C-03: invoked as `python scripts/oversight/suspension_manager.py --check`
  in the transition gate suite, after the inner loop and before second review.
  **OQ-10:** identify the exact transition-suite script. Candidates on disk:
  `scripts/framework/run_tests_inner_loop.sh`, `scripts/framework/run_tests.sh`,
  or `run_second_review.sh`'s caller. The spec leaves the exact insertion point
  to technical-design "in relation to the existing gate-suite ordering" — needs
  the architect to name the canonical transition-suite entrypoint.
- REQ-C-04: unattended (autonomous worker) mode → non-zero exit blocks PR open.
  The worker's pre-PR gate must treat this command's non-zero exit as blocking
  (cross-ref `SPEC-317-worker-pre-pr-gate.md`).
- REQ-C-05: interactive mode → display the mismatch and prompt for confirmation;
  does not auto-block. **OQ-13:** the suspension_manager.py is non-interactive
  (a validator). "Prompt the human" implies the *caller* (worker/runner) handles
  interactivity, not the Python script. Design: `suspension_manager.py --check`
  always exits non-zero on mismatch (deterministic); the *interactive caller*
  decides to prompt-and-continue vs block. Confirm this division.

### Acceptance-criteria trace (§4)

AC-C-01/02 → orphan detection both directions. AC-C-03 → clean → exit 0, OK.
AC-C-04 → worker blocks `gh pr create`. AC-C-05 → transition suite treats
non-zero as failure.

---

## §5 — Suspension format parser unification (#303 Finding 5)

### Critical finding: the bug described in the spec may already be fixed

SPEC §5 / Finding 5 states `check_suspension.sh` "does not parse `[pinned]` and
`review-by:` flags and treats any line containing them as a non-match." **The
current `check_suspension.sh` (lines 39–40) already handles flags** — its grep is:

```
grep -Eq "^SUSPENDED:[[:space:]]*${gate}([[:space:]]+\[pinned\]|[[:space:]]+review-by:[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2})*[[:space:]]*$"
```

with a comment citing **HOS#105** ("Two parsers, one grammar") — the exact fix
the spec asks for appears already landed. **OQ-14 (must resolve before coding
§5):** is Finding 5 a *regression* report against an older `check_suspension.sh`,
already remediated by HOS#105, such that §5 reduces to (a) confirming the
delegation refactor REQ-F-02 still wants the script to call
`suspension_manager.py --is-suspended`, and (b) adding the regression test
REQ-F-06? Or is there a *different* `check_suspension.sh` (e.g. a copy shipped to
consumers, or an inline parser elsewhere) that still has the old bug? The coder
must not "fix" an already-correct parser. Architect/pm to confirm the actual
current-state of the bug.

Given that uncertainty, the design specifies the **REQ-F refactor regardless**
(it is the spec's intent: one canonical parser, delegation, regression test),
because even if the grep is currently correct, REQ-F-01/F-02 want the duplicated
grammar collapsed to a single source of truth.

### Component map

| Component | File | Change |
|---|---|---|
| `--is-suspended` subcommand | `scripts/oversight/suspension_manager.py` | New subcommand: exit 0 if gate suspended (any flags), exit 1 otherwise, quiet |
| Delegation | `scripts/oversight/gates/check_suspension.sh` | Replace inline grep in `is_suspended()` with a call to `suspension_manager.py --is-suspended` |
| Regression test | `tests/oversight/test_suspension_manager.py` (and/or a gate test) | `SUSPENDED: portability [pinned]` → detected as suspended |

### REQ-F-03 — `--is-suspended <gate>` subcommand

Add to `suspension_manager.py`'s argparse:

```python
parser.add_argument("--is-suspended", metavar="GATE", default=None)
```

Behavior (REQ-F-03):
1. Read `contract/gate-suspension.md`.
2. `gates = {s.gate for s in parse_suspensions(text)}` (reuses the existing
   `_SUSPENDED_RE` canonical parser — honors `[pinned]`/`review-by:` already).
3. Exit `0` if `<gate>` ∈ gates, else exit `1`. No stdout (quiet).

Note `_SUSPENDED_RE` already matches `[pinned]` and `review-by:` flags and
extracts the bare gate name (lines 57–60, 98–104) — so `--is-suspended portability`
returns 0 for `SUSPENDED: portability [pinned]` with no new parsing logic
(AC-F-03). This is the canonical parser the spec wants every tool to delegate to.

When `--is-suspended` is passed, the program runs *only* that check and exits
(it does not run census/check/auto-remove). The argparse handler must branch on
`args.is_suspended is not None` before the `run_all` logic.

### REQ-F-02 — check_suspension.sh delegation

Replace the inline grep in `is_suspended()` with delegation:

```bash
is_suspended() {
    local gate="$1"
    local mgr
    mgr="$(_find_suspension_manager)"   # resolves scripts/oversight/suspension_manager.py from repo root
    if [[ -n "$mgr" && -f "$mgr" ]]; then
        python3 "$mgr" --is-suspended "$gate"   # exit 0 = suspended, 1 = not
        return $?
    fi
    # Fallback: the existing inline grep (kept as a fallback ONLY if python3 or
    # the manager is unavailable) — see OQ-15.
    [[ -z "$_SUSPENSION_FILE" ]] && _SUSPENSION_FILE=$(_find_suspension_file)
    [[ -f "$_SUSPENSION_FILE" ]] || return 1
    grep -Eq "^SUSPENDED:[[:space:]]*${gate}(...)*[[:space:]]*$" "$_SUSPENSION_FILE"
}
```

**OQ-15:** the spec's Implementation Notes flag the subprocess overhead of
calling python3 on *every* gate invocation, and offer the alternative of
mirroring the grammar in bash with a comment pointing at the canonical function.
The architect must choose:
  (a) **Delegate** to `suspension_manager.py --is-suspended` (spec's "preferred"
      per REQ-F-02) — single source of truth, subprocess cost per gate call.
  (b) **Mirror** the grammar in bash, with a comment naming `_SUSPENDED_RE` /
      `parse_suspensions` as the canonical source (spec's allowed alternative).
Design's recommendation: (a) delegate, because the gate scripts already shell out
liberally and the safety value of a single parser outweighs one subprocess per
gate. Keep the bash grep as a **fallback** only for environments without python3
(so a gate never silently treats a suspended gate as live because python is
missing — fail toward "suspended" detection working). Architect to decide.

### REQ-F-04/F-05 — `[pinned]` / `review-by:` semantics

Already enforced by the canonical parser path:
- `[pinned]` → `Suspension.pinned` true → excluded from `--auto-remove` (existing
  `cmd_auto_remove` eligibility check, line 236). AC-F-05 already holds.
- `review-by:` → `--census` warns when past (existing `cmd_census`, line 205).
  AC-F-07 already holds.
No new code for F-04/F-05; the requirement is that the *delegation path* (F-02/F-03)
routes through this canonical parser so these semantics are never bypassed by a
secondary parser. Confirmed by REQ-F-02 delegation.

### REQ-F-06 — regression test

Add to `tests/oversight/test_suspension_manager.py` (and a gate-level test if a
bash gate test harness exists — OQ-16):

```python
def test_is_suspended_honors_pinned_flag(tmp_path, monkeypatch):
    # SUSPENDED: portability [pinned] must be detected as suspended.
    susp = "## Currently suspended\nSUSPENDED: portability [pinned]\n"
    # write to contract/gate-suspension.md within a tmp repo root; cd there
    # assert suspension_manager.py --is-suspended portability exits 0
```

Plus, if there is a bash gate-test harness, a test that
`check_suspension.sh portability` (or the sourced `is_suspended portability`)
reports suspended for `SUSPENDED: portability [pinned]` (AC-F-01, AC-F-06).
The test must remain permanently (REQ-F-06).

**OQ-16:** locate or create the bash gate test harness. `tests/oversight/` holds
pytest; there is no obvious bash test for `check_suspension.sh`. The architect/
test role must decide whether the regression test for the *bash* path
(`check_suspension.sh`) is (a) a pytest that invokes the bash script via
subprocess, or (b) a new bash test file, and where it lives. Per the design's
routing-hub role, this is an *untestable-as-specified* gap I am flagging to the
test roles via the architect.

### Acceptance-criteria trace (§5)

AC-F-01/F-02 → check_suspension.sh reports suspended with flags (via delegation).
AC-F-03/F-04 → `--is-suspended` exit codes. AC-F-05 → `[pinned]` not auto-removed
(existing). AC-F-06 → regression test present. AC-F-07 → census warns on past
review-by (existing).

---

## Startup-gap analysis

- §1 (version-skip): **yes, a startup gap** — the installer was shipped assuming
  a sequential prior version; the skip case was never guarded. `startup-artifact-gap`.
  **Affected sign-offs:** any consumer install that *already* version-skipped
  under the old installer produced a content-incomplete install with an
  overstated `.hos-release`. Those installs are orphaned: their recorded tag does
  not match content. The content-currency check (REQ-U-05) is the remediation
  detector; field consumers must re-run with `--full`. Prior installer sign-offs
  for the sequential path stand; the skip path was never reviewed because it was
  never modeled.
- §2 (CORE strip): the broken internal-path citations shipped to consumers from
  day one. `startup-artifact-gap`. Prior agent-content sign-offs were against the
  *HOS-internal* copy (where the paths resolve); the consumer-facing degradation
  was never reviewed. No code re-review needed — this is a packaging fix — but
  any prior assertion that "shipped CORE == reviewed CORE byte-exact" is now
  false (the installer mutates CORE); the architect must accept that invariant
  change (OQ-1 ties in here).
- §3 (pack tokens): additive; bare example paths were a known imprecision, not a
  reviewed-then-broken contract. Prior sign-offs stand.
- §4/§5 (suspension): §5 is explicitly a **safety-relevant** correctness fix
  (#303 Finding 5). If OQ-14 confirms the bug is *not* already fixed, then any
  prior run that trusted `check_suspension.sh` on a flagged suspension was a
  silent gate bypass — those runs' "gate suspended as intended" assumptions are
  orphaned and the affected gates may have *run* when the human believed them
  suspended (or the reverse). The regression test (REQ-F-06) locks the fix.

---

## Consolidated open questions for the architect

| # | Question | Blocks | Provisional choice | Route |
|---|---|---|---|---|
| OQ-1 | §1↔§2: how do SHA256SUMS and CORE-line-stripping compose? | §1, §2 (both) | (a) hash post-strip CORE; share the strip fn between cut_release.sh and installer | architect |
| OQ-2 | Confirm the releases-API repo slug (`thurlow-research/HumanOversightSystem`?) | §1 | use as cited | architect |
| OQ-3 | Trust GitHub release order, or semver-sort defensively? | §1 adjacency | trust order | architect |
| OQ-4 | Does the current installer compute a delta vs prior release, or is every install wholesale? | §1 `--full` semantics | wholesale; `--full` = skip stop only | architect |
| OQ-5 | Canonical region serialization for hashing — reuse `regions.py region_sha`? | §1 | yes, reuse it | architect |
| OQ-6 | `SHA256SUMS` asset absent for target release → hard-stop or warn-skip? | §1 | warn-skip absent, hard-stop on mismatch | architect |
| OQ-7 | Blank-line collapse: CORE-scoped or whole-file? | §2 | CORE-scoped | architect |
| OQ-8 | Keep `{{...}}` engine fully separate from `{NAME}` placeholders.manifest engine? | §3 | yes, separate | architect |
| OQ-9 | Is tokenizing `packs/django/*.md` in this build step or a separate pack-author task? | §3 AC-S-01 | flag as pack-author task | pm-agent / architect |
| OQ-10 | Exact transition-gate-suite entrypoint to invoke `--check` | §4 | name needed | architect |
| OQ-11 | Should `--check` now exit non-zero on consistency mismatch (changes today's exit semantics)? Or new `--check-consistency`? | §4 | extend `--check` per spec | architect |
| OQ-12 | Which "Currently suspended" *table* does `parse_table_gates` target — does the template need one added? | §4 (blocking) | confirm table exists/added | architect / pm-agent |
| OQ-13 | Interactive-mode prompting lives in the caller, not the Python validator? | §4 | yes, caller | architect |
| OQ-14 | Is the §5 `check_suspension.sh` flag-parsing bug already fixed by HOS#105, or is there another buggy parser? | §5 (blocking) | refactor regardless | pm-agent / architect |
| OQ-15 | check_suspension.sh: delegate to python (subprocess/gate) vs mirror grammar in bash? | §5 | delegate, bash fallback | architect |
| OQ-16 | Where does the bash-path regression test for check_suspension.sh live? | §5 AC-F-01/F-06 | flag to test roles | architect → test roles |

**Status:** Requesting architect review. **Blocking before coder handoff:**
OQ-1 (§1/§2 hashing-vs-strip composition), OQ-12 (does the suspension doc table
exist), and OQ-14 (is the §5 bug already fixed). These three determine whether
the work is what the spec literally describes or a no-op/refactor.
