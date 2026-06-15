# v0.3.0 — Pack Install/Selection Mechanism: Implementation Technical Design

**Status:** implementation contract for the pack selection/composition mechanism. Companion to `docs/v0.3.0/TECHNICAL-DESIGN.md` (the region/layering contract it extends) — read that first. Derived from and binding on `docs/v0.3.0/ADR-pack-selection.md` (**ADR-031**, ACCEPTED). This document **details** ADR-031 Decisions 1–5, the `regions.py` delta, and the install control-flow delta; it does **not** re-open them.

This is a **design** — exact signatures, formats, schemas, control flow, and invariants. It is not code. It closes `TECHNICAL-DESIGN.md` **Flag #1** (pack selection mechanism) and **Flag #2** (multi-pack guard/permit), which ADR-031 resolved.

**Scope.** The *mechanism* of pack selection and composition only: the one new `regions.py` verb, the `hos_install.sh` wiring, the `packs/<name>/` on-disk contract, how upgrade/switch flow through the existing merge, and the test plan. It does **NOT** author `packs/django/` content (the separate "borg" extraction from CPS agents — spec §10.4) and does **NOT** touch the three-way merge, `plan_upgrade`, the manifest schema, the removed-region sweep, drift hard-stop, or Phase A/B (all region-id-agnostic, all already cover `PACK:<name>` — `TECHNICAL-DESIGN.md` §1.2/§4/§4.5).

**Relationship to the main TD.** Where the main TD §7.1 said "Pack selection mechanism is **out of scope for this design** (Flag #1) — this design assumes the template agent files already carry the correct `PACK:<name>` region," this document supplies the missing front half: how the `PACK:<name>` region *gets into* the staged template before §7.1's blank-install path and §4.5's Phase A run. Everything downstream of step A1 is unchanged.

---

## 0. Terms (additive to main TD §0)

| Term | Meaning |
|---|---|
| **pack** | A named bundle of `PACK:<name>` region bodies that *deepen* shipped agents. On disk: `packs/<name>/`. Not a set of new agent *files* (ADR-031 D5). |
| **pack body file** | `packs/<name>/<agent>.md` — the raw region-body bytes that become the `PACK:<name>` region of `.claude/agents/<agent>.md`. No markers, no front-matter (D2.2). |
| **selected pack(s)** | The pack name(s) resolved at install time from `--pack`/`config.sh PACK=` (Decision 1.1). Zero (core-only), one (supported), or many (permit-but-warn, Decision 4). |
| **inject-pack** | The one new `regions.py` write verb (the delta) that appends a `PACK:<name>` region to a staged template and re-composes. |

---

## 1. `regions.py inject-pack` — the one additive verb

### 1.1 Why a new verb (not bash, not a new function)

ADR-031 §3.2 is binding: the pack body **must** flow through `compose`/`_normalize_body` so its on-disk bytes equal its manifest sha (the D1/§2.6 disk==manifest identity). A bash marker-concat re-implements `compose`'s marker emission and `_normalize_body` and would diverge from `region_sha`. So pack injection is a thin CLI verb backed entirely by the **existing** pure functions (`parse`, `Region`, `compose`, `validate`). **No new pure function and no new logic** — `inject-pack` is bash-wiring glue, exactly like `migrate`/`plan` are thin wrappers (regions.py module docstring).

### 1.2 CLI signature & argparse wiring

Add one subparser to `build_parser()` (regions.py L1273+), placed after the `migrate` subparser for locality (it is the other write-capable composing verb):

```
regions.py inject-pack <staged-template-file> --name <pack> --body-file <path> [--in-place]
```

argparse wiring (mirrors the `migrate` subparser exactly — positional file, a required option, the shared `--in-place`):

```python
ij = sub.add_parser(
    "inject-pack",
    help="append a PACK:<name> region (body from --body-file) to a staged "
         "template and re-compose (TD-pack §1; ADR-031 §3.2)",
)
ij.add_argument("file", metavar="staged-template-file",
                help="the staged (already-substituted) CORE template to inject into")
ij.add_argument("--name", required=True,
                help="pack slug ([a-z0-9][a-z0-9-]*) — becomes the PACK:<name> region id")
ij.add_argument("--body-file", required=True,
                help="raw region-body bytes for the PACK:<name> region (packs/<name>/<agent>.md)")
ij.add_argument("--in-place", action="store_true",
                help="rewrite the staged file instead of printing to stdout")
ij.set_defaults(func=_cmd_inject_pack)
```

The `<name>` form is a `--name` *required option* (not a positional) so the verb reads identically to `migrate --ships`; the `--in-place`/stdout convention is identical to `migrate` and `compose` (the other write-capable verbs, main TD §2.7: "All subcommands that *could* write take an explicit `--in-place` flag; without it they print to stdout").

### 1.3 Control flow (`_cmd_inject_pack`)

Exact ordering, matching the existing handler shape (`_cmd_migrate` is the template):

```
1. data       = _read_file(args.file)                # staged CORE template bytes
   body        = _read_file(args.body_file)          # pack body bytes (raw, no markers)
     - _read_file raises FileNotFoundError → main()'s handler prints
       "file not found: <path>" and returns EXIT_USAGE (1). Covers BOTH an
       unreadable staged file and an unreadable --body-file with no new code.

2. validate the slug:  if not re.fullmatch(_PACK_SLUG, args.name):
       stderr "invalid pack name '<name>' — must match [a-z0-9][a-z0-9-]*"
       return EXIT_INVALID (2)
     - _PACK_SLUG already exists (L73). Use re.fullmatch (anchor both ends).

3. parsed = parse(data)                              # may raise ParseError
     - on ParseError: stderr "<file>: parse error <e>"; return EXIT_INVALID (2)
       (same as _cmd_compose / _cmd_region_sha).

4. pack_region = Region(
       id=f"PACK:{args.name}", name=args.name, body=body,
       start_line=0, end_line=0,
   )
   regions = list(parsed.regions) + [pack_region]
   merged  = ParsedAgent(front_matter=parsed.front_matter, regions=regions,
                         raw=parsed.raw)

5. out = compose(merged)
     - compose() alpha-orders via _canonical_order_key: CORE -> PACK(alpha) ->
       PROJECT. Injection ORDER IS IRRELEVANT — a second inject-pack on the
       result re-sorts. _normalize_body is applied to the pack body here, so the
       injected region's on-disk bytes == its region_sha (the §2.6 identity).

6. RE-VALIDATE the result (the must-re-validate rule, ADR-031 delta):
       check = validate(parse(out))
       if not check.ok:
           for line, code, msg in check.errors:
               stderr f"{line}:{code}:{msg}"
           return EXIT_INVALID (2)
     - This is where a DUPLICATE pack name surfaces: injecting PACK:django into
       a template that ALREADY has a PACK:django region yields two PACK:django
       regions → validate() emits E_DUP_PACK → EXIT_INVALID. No new error code;
       E_DUP_PACK + EXIT_INVALID ARE the "E_DUP_PACK" the ADR delta names.

7. emit (the --in-place/stdout split, byte-exact from _cmd_migrate):
       if args.in_place:
           with open(args.file, "wb") as fh: fh.write(out)
       else:
           sys.stdout.buffer.write(out)
       return EXIT_OK (0)
```

**Note on re-validation:** we `validate(parse(out))` rather than `validate(merged)` because `compose` is the canonicalizing writer and re-parsing its output is the truest check that what we *wrote* is well-formed (round-trip). It also catches a malformed pack body that smuggled a literal marker line (`E_LITERAL_MARKER_IN_BODY`) — a body file is supposed to be marker-free (D2.2), and this is the fail-closed catch if an author violates that.

**N1 — why `E_DUP_PACK` cannot fire on a normal re-install (and re-install is idempotent).** The `E_DUP_PACK` guard at step 6 protects against a *double-inject into one template* — two `PACK:django` regions in the same staged file. But the installer **never performs** that double-inject: A1b (§2.4) always injects into a **freshly-staged CORE-only template** that is re-staged from the HOS source (`_substitute_into "$src" "$_stage"`, then flat-wrap) on **every** install run. The staged template therefore **never pre-carries** a `PACK:<name>` region before A1b runs, so injecting `PACK:django` once produces exactly one such region — `E_DUP_PACK` is structurally unreachable on the installer's own path, and the guard exists only to fail-closed a hand-built or scripted double-inject (and to back the §5.1 unit test). Idempotency of a re-install (same pack, no version bump) therefore comes **not** from inject-pack dedup but from the **downstream three-way**: the freshly-staged CORE+PACK template is compared against the *disk* file's CORE+PACK regions, and an unchanged body yields `disk == incoming` → **KEEP/REFRESH** (§4.1 row 1/2), writing the same bytes back. Re-installing the same pack is a fixed point because the staging is rebuilt-from-source each run and the merge re-converges, not because inject-pack detects a prior install.

### 1.4 Error / exit semantics (summary table)

| Condition | stderr | Exit |
|---|---|---|
| staged file or `--body-file` unreadable | `file not found: <path>` (via `main()`) | `EXIT_USAGE` (1) |
| `--name` not a valid slug | `invalid pack name '<name>' — must match [a-z0-9][a-z0-9-]*` | `EXIT_INVALID` (2) |
| staged template fails to parse | `<file>: parse error <e>` | `EXIT_INVALID` (2) |
| result fails to validate (incl. **duplicate pack → `E_DUP_PACK`**, literal marker in body → `E_LITERAL_MARKER_IN_BODY`) | `<line>:<CODE>:<msg>` per error | `EXIT_INVALID` (2) |
| success | — | `EXIT_OK` (0) |

These reuse the existing `EXIT_USAGE`/`EXIT_INVALID`/`EXIT_OK` constants (regions.py L58–61) — **no new exit code**. ADR-031's "`E_DUP_PACK` → `EXIT_INVALID`" is satisfied by the existing `validate()` invariant 5 (regions.py L414–426) firing on the re-validate.

### 1.5 What does NOT change in regions.py

- **No change** to `parse`, `compose`, `Region`, `ParsedAgent`, `_canonical_order_key`, `_normalize_body`, `validate`, `merge_region`, `plan_upgrade`, `manifest_rows`, `_plan_manifest_rows`, `assemble_manifest`, `migrate_flat`, `base_shas_for_path`, or any exit-code constant.
- **No new pure function.** `inject-pack` is a CLI handler (`_cmd_inject_pack`) + one subparser. All composition logic is the existing `compose`; all validation is the existing `validate`; the slug grammar is the existing `_PACK_SLUG`.
- **No schema/manifest/migration change.** `PACK:<name>` is already a first-class region everywhere (regions.py treats it as such in `_canonical_order_key`, `validate` invariant 5, `manifest_rows`, the merge, the removed-sweep).
- **`compose` is unchanged** — it already alpha-orders PACK regions and normalizes bodies. `inject-pack` relies on that pre-existing behavior; it does not extend it.

> **Sub-decision (ADR silent):** ADR-031 §3.2/delta shows the verb constructing `Region(..., start_line=0, end_line=0)` but does not state whether to validate the *slug* inside the verb. I add the explicit slug check (step 2) because `--name` is operator/installer input and an invalid slug would otherwise produce a `PACK:<garbage>` region whose markers `validate()` rejects only indirectly. Failing early at step 2 with a clear message is the fail-closed choice and costs one `re.fullmatch`. CONFIDENCE: high — it cannot change any valid-input behavior (valid slugs always pass).

---

## 2. `hos_install.sh` wiring

All changes are in `bootstrap/hos_install.sh`. The numbered steps below are implementable against the **current** file (line refs are to the version read for this design).

### 2.1 Arg additions (arg-parse block, L71–87)

Add three cases to the `while`/`case` block, alongside `--squash`/`--prune`:

```bash
--pack)          _packs+=("${2:?--pack needs a name, e.g. --pack django}"); shift 2 ;;
--pack=*)        _packs+=("${1#*=}"); shift ;;
--no-pack)       NO_PACK=true; shift ;;
```

Declare defaults in the `── Defaults ──` block (L58–68), next to `PRUNE=`/`SQUASH=`:

```bash
NO_PACK=false        # --no-pack: install bare core, no pack (deliberate; #237 WARN)
_packs=()            # --pack <name> (repeatable). Empty ⇒ resolve from config.sh PACK=.
```

`_packs` is an array (repeatable `--pack`, per Decision 4: "`--pack` accepts repetition (append to a `_packs` array)"). Add a one-line `--pack <name>` / `--no-pack` entry to the `# Usage:` header comment block (L10–28) so `--help` (which `sed`s L2–41) documents them.

**Mutual-exclusion check** — immediately after the arg loop (after L87, before the `TARGET_REPO` resolve), so a bad invocation fails before any work:

```bash
if $NO_PACK && [[ ${#_packs[@]} -gt 0 ]]; then
  echo "ERROR: --no-pack and --pack are mutually exclusive (try --help)"; exit 1
fi
```

(Uses a bare `echo`/`exit 1` like the other arg errors at L84/L90 — the `err()` helper is defined later, after colours.)

### 2.2 Pack-resolution block (NEW — before the agent copy-loop)

Placement: a new block **after** the placeholder-substitution SETUP (which ends at L527, where `_subst_config` and the config.sh append idiom are already established) and **before** the Phase-A/B agent flow header at L549 (`info ".claude/agents/ — layered install (region merge)"`). It must run before A1 because A1 consumes `_resolved_packs`.

The block resolves packs and records the choice. Control flow as a decision tree (ADR-031 §1.1/§1.3/Decision 4):

```
# ── Pack resolution (ADR-031 Decision 1) ─────────────────────────────────────
_resolved_packs=()

# (R1) Source of truth: flags win; else config.sh PACK= (the upgrade read-path).
#      CRITICAL: --no-pack must WIN over a recorded config.sh PACK= — gate the
#      config read on `! $NO_PACK`. Without this gate, a flagless `--no-pack`
#      install reads the recorded PACK=django into _resolved_packs, R2's
#      "${#_resolved_packs[@]} -eq 0" guard is then false, the $NO_PACK arm is
#      never reached, and --no-pack is a SILENT no-op (B1). --no-pack is an
#      explicit operator opt-out; it must override the recorded choice.
if [[ ${#_packs[@]} -gt 0 ]]; then
    _resolved_packs=("${_packs[@]}")               # from --pack (precedence 1)
elif ! $NO_PACK && [[ -f "$_subst_config" ]]; then   # --no-pack suppresses the config read
    _cfg_pack="$(grep -E '^PACK=' "$_subst_config" 2>/dev/null | head -1 \
                  | cut -d= -f2- | sed 's/^"//; s/"$//')"
    [[ -n "$_cfg_pack" ]] && _resolved_packs=("$_cfg_pack")   # precedence 2 (single-value)
fi
# NB: v0.3.0 reads config.sh PACK= as a SINGLE value (ADR-031 "open seams"); the
# space-split multi-value form is a noted-not-built seam. Repeated --pack is the
# only wired multi-pack path.

# (R2) No pack resolved → the no-pack decision tree (ADR-031 §1.3).
if [[ ${#_resolved_packs[@]} -eq 0 ]]; then
    if $NO_PACK; then
        # explicit opt-out → core only, #237 WARN (bare core IS a real install).
        warn "installing bare core with no pack — core enforces generic best"
        warn "practices but is shallow; install a pack before first real use"
        # (R2a) --no-pack must also CLEAR a recorded config.sh PACK= (B1 follow-on).
        # Else the NEXT flagless install reads the stale PACK= and silently re-adds
        # the pack the operator just stripped — a footgun. Blank/remove the row so
        # the recorded state matches the installed state (bare core).
        if [[ -f "$_subst_config" ]] && grep -qE '^PACK=' "$_subst_config" 2>/dev/null; then
            _old_pack="$(grep -E '^PACK=' "$_subst_config" | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
            if $DRY_RUN; then dry_run "Would clear config.sh PACK=\"$_old_pack\" (--no-pack strip)"
            else perl -i -ne 'print unless /^PACK=/' "$_subst_config"; fi
            warn "config.sh PACK cleared: $_old_pack → (none) — pack stripped (see removed-region sweep)"
        fi
    elif [[ -t 0 ]]; then
        # interactive, no --no-pack → S1 hard default: don't ship core-only by accident.
        err "no PACK selected — pass --pack <name> (e.g. --pack django), set PACK="
        err "in scripts/framework/config.sh, or pass --no-pack to install the bare"
        err "core deliberately"
        exit 1
    else
        # non-interactive / CI, no --no-pack → CI must be explicit (error path).
        err "no PACK selected and not interactive — CI must pass --pack <name> or"
        err "--no-pack explicitly"
        exit 1
    fi
fi

# (R3) Validate each resolved pack exists in the HOS source (unknown → hard error,
#      fail-closed: nothing written, exit non-zero — never fall through to core-only).
for _p in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
    if [[ ! -d "$HOS_SOURCE/packs/$_p" ]]; then
        err "unknown pack '$_p' — no packs/$_p/ in the HOS source ($HOS_REF)"
        err "available: $(cd "$HOS_SOURCE/packs" 2>/dev/null && ls -d */ 2>/dev/null \
              | tr -d / | tr '\n' ' ' || echo '(none)')"
        exit 1
    fi
done

# (R4) Multi-pack → permit, but WARN once (Decision 4 — untested composition).
if [[ ${#_resolved_packs[@]} -gt 1 ]]; then
    warn "multiple packs selected (${_resolved_packs[*]}) — multi-pack composition"
    warn "is UNTESTED in v0.3.0 (alphabetical order, no conflict resolution);"
    warn "single-pack is the supported path"
fi
```

**Decision-tree summary (matches ADR-031 §1.3 exactly):**

| State | Interactive? | `--no-pack`? | Outcome |
|---|---|---|---|
| pack resolved (flag or config) | — | — | proceed with pack(s) |
| no pack | yes | no | **ERROR exit** (S1 hard default) |
| no pack | — | yes | **core-only + #237 WARN**; clears a recorded `config.sh PACK=` (R2a) and the staged template carries no PACK region → on a prior install that had `PACK:<name>`, the removed-region sweep STRIPs it (DROP if unedited / HARDSTOP if edited — §4.2) |
| no pack | no (CI) | no | **ERROR exit** (CI must be explicit) |
| unknown `packs/<name>/` | — | — | **hard error** (fail-closed) |
| >1 pack | — | — | proceed + **multi-pack WARN** (once) |

### 2.3 Recording the choice — `config.sh` `PACK="<name>"` append

ADR-031 §1.2: write `PACK="<name>"` to `config.sh` when a **single** pack resolved **from a flag** and the key is absent/differs. Reuse the existing append idiom — the placeholder-key append loop at **L511–515**:

```bash
for _n in "${_names[@]}"; do
  if [[ -f "$_subst_config" ]] && grep -qE "^${_n}=" "$_subst_config" 2>/dev/null; then continue; fi
  if $DRY_RUN; then dry_run "Would append ${_n}=\"\" to config.sh"; else printf '%s=""\n' "$_n" >> "$_subst_config"; fi
  _appended+=("$_n")
done
```

Add this, inside the pack-resolution block, **after (R3)** (only record validated packs) and gated on "single pack, from a flag":

```bash
# (R5) Record the choice for upgrade reuse (ADR-031 §1.2). Only when a SINGLE
#      pack came from --pack (config-as-source needs no rewrite). config.sh is
#      consumer-owned and append-only here — overwrite ONLY when PACK= differs.
if [[ ${#_packs[@]} -eq 1 ]]; then
    _pk="${_packs[0]}"
    if [[ ! -f "$_subst_config" ]]; then
        if $DRY_RUN; then dry_run "Would create config.sh with PACK=\"$_pk\""
        else mkdir -p "$(dirname "$_subst_config")"; printf 'PACK="%s"\n' "$_pk" >> "$_subst_config"; fi
    elif grep -qE '^PACK=' "$_subst_config" 2>/dev/null; then
        _cur="$(grep -E '^PACK=' "$_subst_config" | head -1 | cut -d= -f2- | sed 's/^"//; s/"$//')"
        if [[ "$_cur" != "$_pk" ]]; then
            if $DRY_RUN; then dry_run "Would update config.sh PACK=\"$_cur\" → \"$_pk\""
            else perl -i -pe "s|^PACK=.*|PACK=\"$_pk\"|" "$_subst_config"; fi
            warn "config.sh PACK changed: $_cur → $_pk (a pack switch — see removed-region sweep)"
        fi
    else
        if $DRY_RUN; then dry_run "Would append PACK=\"$_pk\" to config.sh"
        else printf 'PACK="%s"\n' "$_pk" >> "$_subst_config"; fi
    fi
fi
```

> **Sub-decision (ADR partially silent on the overwrite mechanic):** ADR-031 §1.2 says "append-if-absent, overwrite-if-`--pack`-given-and-differs" but the existing append idiom only *appends*. The overwrite case needs an in-place edit; I use `perl -i -pe` (already the installer's substitution engine, L537 — no new dependency) anchored on `^PACK=`. The append-when-absent and create-when-no-file cases reuse the L511–515 idiom verbatim. Multi-pack from flags is **not** recorded to `config.sh` (the single-value `PACK=` seam is all v0.3.0 wires — Decision 4); a multi-pack upgrade must re-pass `--pack` each time, which is acceptable for the untested path. CONFIDENCE: high.

### 2.4 The A1 staging change (replace the flat-wrap stub)

> **Round-2 note on line refs.** The L5xx/L6xx line numbers in §2.1–§2.4 below are from the original (pre-implementation) installer the round-1 design was written against. The coder has since landed A1b (and the arg/resolution wiring) **live** — in the current `hos_install.sh`, A1 flat-wrap is ~L686–698, A1b ~L700–714, A4 plan ~L744–778, and the decide-all-then-act gate ~L781–790. The round-2 fixes (B1 §2.2 R1/R2a, B2 §2.4.1) are therefore **deltas against the already-live code**, not net-new insertions; treat the original line refs as locating-the-region hints and the §2.4.1 / L7xx refs as the authoritative current positions.

ADR-031 §3.1 step 4: inject the pack **after** substitute + flat-wrap, **before** `plan`. The current A1 stub is at **L591–603** (live: ~L686–698):

```bash
# (A1) stage + substitute the template (D6 — substitute BEFORE plan).
_stage="$_AGENT_STAGE/${agent}.tmpl.md"
_substitute_into "$src" "$_stage"
# Forward-compat: ... flat template → wrap as CORE ...
if ! grep -q '<!-- HOS:' "$_stage" 2>/dev/null; then
  _stage_wrapped="$_AGENT_STAGE/${agent}.tmpl.wrapped.md"
  if python3 "$_REGIONS_PY" migrate "$_stage" --ships yes > "$_stage_wrapped" 2>/dev/null; then
    mv "$_stage_wrapped" "$_stage"
  fi
fi
```

**Insert immediately after the flat-wrap block (after L603), still inside the `for agent in` loop:**

```bash
# (A1b) Pack injection (ADR-031 §3.1 step 4). For each selected pack that
# deepens THIS agent (packs/<pack>/<agent>.md exists), inject its PACK:<pack>
# region into the staged CORE template. compose() (inside inject-pack) re-sorts
# alphabetically, so injection order is irrelevant. An agent with no pack file
# stays CORE-only (the absence is the signal — D2.2). Placeholder-free bodies
# are NEVER substituted (D6) — they are injected raw, post-substitution.
for _pk in ${_resolved_packs[@]+"${_resolved_packs[@]}"}; do
  _body="$HOS_SOURCE/packs/$_pk/${agent}.md"
  [[ -f "$_body" ]] || continue
  if ! python3 "$_REGIONS_PY" inject-pack "$_stage" \
        --name "$_pk" --body-file "$_body" --in-place 2>/dev/null; then
    fail "inject-pack $_pk into ${agent} failed — check packs/$_pk/${agent}.md"
    _any_inject_fail=true   # B2: route through the pre-Phase-B abort gate (below)
    continue 2              # skip this agent; an unwritable pack region must not ship half-composed
  fi
done
```

Declare the sentinel `_any_inject_fail=false` alongside `_any_blocked=false` (hos_install.sh L665), inside the Phase-A setup.

Notes binding the coder:
- `--in-place` rewrites `$_stage` so the subsequent `plan` (A4, L753) sees the CORE+PACK staged template with no further change to A2–A5.
- The flat-wrap (A1) runs **first** so `$_stage` always has a CORE region before injection; `inject-pack` appends the PACK region to a valid CORE template. (If templates are still flat in the pilot, A1 wraps to CORE, then A1b injects PACK — exactly ADR-031 §3.1's ordering.)
- `continue 2` (skip this agent's remaining Phase-A work) is correct for *this agent* — but skipping the agent is **not** sufficient on its own. The `fail` increments `ERRORS`, which is only checked at the SUMMARY (L1258) — *after* Phase B has already written every other agent + `.hos-manifest` + `.hos-release`. So `continue 2` alone yields a **partial install** (B2). The `_any_inject_fail=true` sentinel + the gate change in §2.4.1 below is what makes the *install* fail-closed; `continue 2` only makes *this one agent* not-half-composed. The two are different invariants — see §2.4.1.

### 2.4.1 Pre-Phase-B abort gate (B2 — the fail-closed invariant)

**The bug (B2).** The drift path is correctly fail-closed: A4's `_plan_rc == 4` sets `_any_blocked=true; continue` (L761/L770), and the decide-all-then-act gate at L781–790 checks `$_any_blocked` and `exit 4` **before** Phase B (L792) — so a drift hard-stop writes **nothing**. The inject path (A1b) and the **existing** A4 `_plan_rc != 0` path (L771–773) both do `fail; continue` with **no sentinel** and therefore **fall through** that gate into Phase B → every *other* agent + `.hos-manifest` + `.hos-release` get written → **partial install**. The §2.4 "fail-closed" claim above (round 1) was therefore false: skipping one agent is not the same as a fail-closed install.

**The fix — reuse the one decide-all-then-act gate; do not invent a second exit path.** Extend the existing gate (L781–790) to also abort when any inject failed, alongside `$_any_blocked`:

```bash
# ── Decide-all-then-act gate (§4.3 + B2) ────────────────────────────────────
if $_any_blocked || $_any_inject_fail; then
  echo ""
  if $_any_blocked; then
    err "Layering drift — refusing the whole upgrade (nothing written, no version stamped):"
    printf '%s' "$_blocked_report"
    echo ""
    err "Re-run with --squash to take HOS's version of the drifted region(s), or move"
    err "your edits into each file's PROJECT region, then re-run."
  fi
  if $_any_inject_fail; then
    err "Pack injection failed for one or more agents (see errors above) — refusing the"
    err "whole install (nothing written, no manifest, no version stamped). Fix the named"
    err "packs/<pack>/<agent>.md and re-run."
  fi
  # exit 4 = the layering/abort hard-stop code (shared with drift). Phase B is BELOW;
  # nothing in .claude/agents/, .hos-manifest, or .hos-release is written.
  exit 4
fi
```

Binding the coder:
- The abort lands **before** Phase B (L792) — identical placement to the drift gate. Because the gate runs after the **whole** agent loop, the run still names *every* failed agent (`fail` printed each), matching the decide-all-then-act posture; it just refuses to write any of them.
- **Route BOTH `fail;continue` agent-loop paths through this one gate.** The A4 `_plan_rc != 0` path (L771–773, "planning … failed") has the **same** half-write defect — it does `fail; continue` with no sentinel and falls through into Phase B. The B2 installer fix should set the same sentinel on that path too (e.g. `_any_inject_fail=true` there, or a parallel `_any_plan_fail`), so there is exactly **one** pre-Phase-B abort gate covering inject failure, plan failure, and drift. (The A4 `_plan_rc != 0` half-write **predates this design** — it is a pre-existing latent bug, flagged in §6; B2's installer change is the natural place to route it through the gate, but the A4 bug itself is not introduced by the pack mechanism.)
- `exit 4` is reused (the existing layering hard-stop code) rather than a new code — there is **one** abort path, not two. The SUMMARY's `ERRORS>0 → exit 1` (L1258) is now unreachable for inject/plan failures because the gate exits first; it remains the catch-all for any non-loop `fail` (e.g. a later Phase-B write error).

### 2.5 What is confirmed untouched (guardrails)

Per ADR-031 §3.1 step 5 / §3.3 / §3.4 and the "What this does NOT change" section, these are **not modified**:
- **Phase A (A2–A5):** disk prep, base-shas read, `plan`, plan stash — unchanged. `plan` now sees a CORE+PACK staged template; `plan_upgrade` treats `PACK:<name>` as a first-class HOS-owned region with no special-casing (the PACK region routes through the identical `merge_region` / freshly-introduced-REFRESH path as CORE — main TD §4.5, regions.py `plan_upgrade` L774–808).
- **Phase B:** composition + write + manifest spec — unchanged. The composed file's `PACK:<name>` rows are emitted by `_plan_manifest_rows` with no change (ADR-031 §3.3).
- **Manifest:** `enumerate_framework_files` (WHOLE rows) + `assemble_manifest` — unchanged. PACK rows arrive via the same agent plan spec as CORE/PROJECT rows (L1033–1045).
- **Drift hard-stop / removed-region sweep / `--squash` / `--prune`:** unchanged and already region-id-agnostic (they cover `PACK:<name>` today — main TD §4.2 rows 4–6).
- **Substitution boundary (D6):** `perl` runs over CORE in the staged template *before* `inject-pack` (A1 before A1b); PACK bodies are injected raw and never substituted.
- **PROJECT never-written invariant:** packs touch only PACK regions (§4.4 holds).

---

## 3. The `packs/<name>/` on-disk contract

### 3.1 Directory layout (ADR-031 §2.1)

```
packs/
  <name>/
    pack.toml                  # metadata (§3.3)
    <agent>.md                 # one file PER agent the pack deepens (§3.2)
    <agent>.md
    ...                        # agents with NO depth here have NO file
```

`packs/` lives at the HOS repo root (sibling of `.claude/`, `scripts/`, `contract/`). It is shipped in the release tarball (it sits under the repo root that `git archive` / the GitHub tarball captures — **no change to `REQUIRED_SOURCE_PATHS`** is required because packs are optional; an install with `--no-pack` must work against a release that has no `packs/`).

> **Sub-decision (ADR silent on release packaging):** the ADR assumes `packs/` is "in the HOS source" but does not state whether it is a *required* source path. I do **not** add `packs/` to `REQUIRED_SOURCE_PATHS` (L169–181): a release legitimately may ship core-only, and the R3 unknown-pack check already fails closed if a `--pack X` names a missing `packs/X/`. Making `packs/` mandatory would break `--no-pack` installs from a core-only release. CONFIDENCE: high.

### 3.2 File → region mapping (ADR-031 §2.2)

- For pack `<name>`, `packs/<name>/<agent>.md` contains **exactly the region body** that becomes the `PACK:<name>` region of `.claude/agents/<agent>.md`.
- **Raw body bytes only — no markers, no front-matter.** The installer (`inject-pack`) wraps it in canonical `<!-- HOS:PACK:<name>:START -->`…`:END -->` via `compose`.
- An agent with **no file** in `packs/<name>/` gets **no `PACK:<name>` region** — the absence is the signal. `ls packs/<name>/` (minus `pack.toml`) **is** the list of agents `<name>` deepens.
- The `<agent>` basename must be a slug in `scripts/framework/consumer_agents.txt` (packs deepen **shipped** agents only — D5). A pack file for a non-shipped slug is silently inert in v0.3.0 (the A1b loop only runs for agents in `_consumer_agents`); the hos-dev lint (§3.5) SHOULD flag it.

### 3.3 `pack.toml` minimal schema (ADR-031 §2.4)

```toml
name = "django"                 # MUST equal the directory name (installer sanity-checks)
description = "Django + HTMX + PostgreSQL stack depth for the base team"
version = "0.1.0"               # semver string; informational in v0.3.0
requires = []                   # optional list of pack slugs; RECORDED, UNUSED in v0.3.0
```

**How the installer reads it (trivial, no TOML dep — ADR-031 §2.4):** v0.3.0 reads **only** `name`, to sanity-check it against the directory name. Grep/cut, matching the `config.sh` value-extraction idiom (install.sh L152, hos_install.sh R1):

```bash
_declared="$(grep -E '^[[:space:]]*name[[:space:]]*=' "$HOS_SOURCE/packs/$_p/pack.toml" 2>/dev/null \
             | head -1 | cut -d= -f2- | sed 's/[[:space:]]*//g; s/^"//; s/"$//; s/^'\''//; s/'\''$//')"
if [[ -n "$_declared" && "$_declared" != "$_p" ]]; then
    warn "packs/$_p/pack.toml declares name=\"$_declared\" but the directory is '$_p' — using '$_p'"
    warn "  fix: rename the directory to '$_declared', or correct name= in pack.toml to '$_p'"
fi
```

> **Sub-decision (ADR says "sanity-check vs dir" without specifying severity) — CONFIRMED by the architect (round 2):** a `name`/dir mismatch is a **WARN, not a hard error** at *consumer install time* — the directory name is authoritative (it is what `--pack` and the on-disk region id key on), and a stale `name=` in `pack.toml` should not block a consumer's install. The WARN names **both** remedies ("rename the directory or correct `name=`") so the operator can act. This is an **author-vs-consumer severity split**: the mismatch is a real defect for the *pack author*, and it becomes a **HARD failure in the hos-dev CI lint** (the `hos-dev-pack` check that validates `packs/*/` before release — §3.5), not in the consumer installer. Authors get a blocking signal; consumers get a non-blocking advisory and the directory-authoritative install. This is placed inside the R3 loop (each validated pack), reusing `HOS_SOURCE`. `requires`/`version`/`description` are **not parsed** in v0.3.0 (forward seam only).

### 3.4 Placeholder-free rule (ADR-031 §2.5, binds main TD D1a/D7)

Pack body files are PACK regions → they **MUST NOT contain install-time placeholders** (`{SPEC_FILE}`, `{PROJECT_NAME}`, `{DESIGN_PACK_DIR}`, `{ADR_FILE}` — the keys in `placeholders.manifest`). Authoring rule for `packs/<name>/*.md`: use **runtime self-direction** ("read the spec path declared in `scripts/framework/config.sh`"), never a `{KEY}` token. This is why A1b injects the body **raw** (no substitution) and the sha model stays config-independent (main TD §3.2: for CORE/PACK `incoming == region_sha(template body)` with no config dependency).

### 3.5 How the hos-dev CI lint enforces §3.4 (ADR-031 §2.5 / main TD D7)

The placeholder ban is enforced on the **composed** agent (not the raw body file), reusing the **existing** `validate --placeholder-keys` (regions.py L294/L1284–1291, the D7 path) — **no new lint code in regions.py**. The hos-dev CI step (a `hos-dev-pack` check, not the consumer installer) runs, for each shipped agent composed with each pack:

```
regions.py inject-pack <CORE-template> --name <pack> --body-file packs/<pack>/<agent>.md \
  | regions.py validate /dev/stdin \
      --placeholder-keys "$(cut -f1 scripts/framework/placeholders.manifest | grep -v '^#' | paste -sd, -)"
```

A `{KEY}` (for any declared placeholder key) inside the composed `PACK:<name>` region → `E_PLACEHOLDER_IN_CORE_PACK` → non-zero exit → CI fails. This is the existing `E_PLACEHOLDER_IN_CORE_PACK` invariant (regions.py L438–447) applied to the composed pack output. (Authoring this CI step itself is a hos-dev-pack concern; the *mechanism* it uses — `inject-pack` then `validate --placeholder-keys` — is fully specified here.)

The same hos-dev CI lint is **also** where a `pack.toml` `name=`/directory mismatch (§3.3) is a **HARD failure** for pack *authors* — the author-vs-consumer severity split. The consumer installer WARNs and proceeds (directory authoritative); the release-gating CI lint rejects the pack until `name=` and the directory agree, so no mismatched pack ever ships. (The lint check itself — a `grep` of `name=` vs the directory basename — is a hos-dev-pack concern; recorded here so the split is unambiguous.)

> **Sub-decision (ADR silent on lint input path):** `validate` takes a file argument; to lint the *composed* output without a temp file, pipe `inject-pack` stdout to `validate /dev/stdin` (or write to a temp and validate that — both work; the pipe is cleaner). The lint is a CI wiring detail, not a regions.py change. CONFIDENCE: high — `validate --placeholder-keys` already exists and does exactly this.

---

## 4. Upgrade & pack-switch paths (no new merge logic)

Both flow through the **existing** `plan_upgrade` / `merge_region` with **zero new code** — this section shows *why*, citing the current behavior.

### 4.1 PACK version bump → REFRESH vs consumer-edited HARDSTOP (D2)

On an upgrade with **the same pack** (resolved from `config.sh PACK=`, §2.2 R1), A1b injects the **new** pack body into the staged template. Then A4's `plan` runs the unchanged three-way per region. For the `PACK:<name>` region (main TD §4.2, regions.py `merge_region` L561–570):

| Disk vs base | Disk vs incoming(new body) | Action | Why no new code |
|---|---|---|---|
| `base == disk` (untouched) | `disk == incoming` | **KEEP** | bump is a no-op; re-stamp `base_sha=incoming` |
| `base == disk` (untouched) | `disk != incoming` | **REFRESH** | version bump lands; write new body, re-stamp |
| `base != disk` (consumer edited PACK) | `disk != incoming` | **HARDSTOP** unless `--squash` | row 4 — drift report names the `PACK:<name>` region (regions.py `_drift_reason`, already region-id-agnostic) |
| `base != disk` | `disk == incoming` (convergent) | **KEEP**/realign | row 3 |

`merge_region` is region-id-agnostic (it only branches on `PROJECT` and `removed`); a `PACK:django` region takes the identical path as `CORE`. The drift report already names whichever region drifted (`_drift_reason(region_id, …)`), so a drifted PACK region produces a precise, correctly-named hard-stop with **no change**.

### 4.2 Pack switch (SWITCH) and pack strip (STRIP) → removed-region sweep DROP/HARDSTOP (D9)

Two shapes route through the **same** removed-region sweep: a **SWITCH** (flask→django) and a **STRIP** (django→none, via `--no-pack`). Both leave a `PACK:<old>` region present on the disk file + prior manifest but **absent from the freshly-staged template** — which is exactly the removed-region sweep input (main TD §4.2 rows 5/6, regions.py `plan_upgrade` L810–828).

**SWITCH (flask→django).** `config.sh` had `PACK="flask"`, now `--pack django` rewrites it to `PACK="django"` (§2.3 R5). A1b injects `PACK:django` and **does not** inject `PACK:flask`. The staged template carries `PACK:django` but **not** `PACK:flask`:

- `PACK:flask` is in `base_shas` (the prior manifest) and **absent from the template** → the manifest-side sweep fires with `removed=True`.
- `base == disk` (consumer never edited the flask region) → **DROP**: `compose` omits the region, its manifest row is removed. The new `PACK:django` region is REFRESH-introduced by the template-side loop (freshly introduced → `disk_sha is None` → REFRESH, regions.py L788–793).
- `base != disk` (consumer edited the flask region) → **HARDSTOP** unless `--squash`/`--prune` (which the installer maps to `squash=True`, main TD §4.5 review note + hos_install.sh L563–566) → then **DROP**.

> **N2 (clean-prior-manifest precondition):** the DROP of `PACK:flask` relies on the prior `.hos-manifest` carrying the `PACK:flask` row — that is what puts `PACK:flask` in `base_shas` so the sweep can see it as removed. A *partial* prior manifest (e.g. one written by a half-completed install) might omit the row, in which case the stale on-disk flask region is invisible to the sweep and silently survives. This clean-manifest guarantee holds **only once B2 is fixed** (an inject failure must write **nothing**, including no partial manifest). The switch test (§5.2) must therefore run against a **cleanly-completed** prior install.

**STRIP (django→none, `--no-pack`).** `config.sh` had `PACK="django"`, now `--no-pack` clears it (R2a) and A1b injects **no** pack at all. The staged template carries **no** PACK region; `PACK:django` is present on disk + prior manifest. This is the **intended strip semantics** — identical to the SWITCH's removed half with no introduced half:

- `PACK:django` in `base_shas`, absent from the template → sweep fires `removed=True`.
- `base == disk` (consumer never edited the django region) → **DROP**: the region is omitted from the composed file, its manifest row removed → the agent reverts to CORE+PROJECT.
- `base != disk` (consumer edited the django region) → **HARDSTOP** unless `--squash`/`--prune` → then **DROP**. A consumer who hand-tuned the pack region is told before their edits vanish; that is the correct fail-closed behavior, not a bug.

So both SWITCH and STRIP are, from the manifest's view, identical to "HOS retired the old region" (SWITCH additionally "introduced a new region") — all handled by code that already exists and is already tested (`test_plan_upgrade.py` DROP/HARDSTOP scenarios). **Zero new merge logic.** The only new things are the `config.sh PACK=` rewrite/clear + switch/strip WARN (§2.3 R5 / §2.2 R2a), which are installer wiring, not merge logic.

### 4.3 Why no new merge logic is required (the load-bearing point)

`regions.py` was authored treating `PACK:<name>` as a first-class HOS-owned region everywhere: `_canonical_order_key` (L578–592), `validate` invariant 5 (L414–426), `manifest_rows` (L654–674), `merge_region`'s non-PROJECT/non-removed branches (L561–570), the removed sweep (L810–828), and `_drift_reason`/`_drop_reason` (region-id-parameterized). The pack mechanism only had to supply *how a PACK region enters the staged template* (`inject-pack` + A1b) and *how the choice is selected/recorded* (§2.2–2.3). Everything from `plan` onward was already pack-aware.

---

## 5. Test plan

Two layers, matching existing conventions: **unit tests** for the `inject-pack` verb (extend `tests/framework/test_regions_cli.py`, the subprocess CLI style, which already has the `_agent`/`_run`/`_write`/`_shas` helpers) and **install-path tests** for the wiring (new `tests/framework/test_pack_install.py`, a bash-driving harness in the style of the existing subprocess tests / the Phase-1 verification). `tests/conftest.py` already puts the validators dir on `sys.path`, so `import regions` works bare.

### 5.1 Unit — `inject-pack` verb (extend `tests/framework/test_regions_cli.py`)

Reuse the file's `_agent`, `_run`, `_write`, `_shas` helpers. Add a 2-region builder (`CORE` + `PROJECT`, no PACK) for the injection-target cases.

| Test | Setup | Assert |
|---|---|---|
| `test_inject_pack_happy_path` | staged CORE+PROJECT template; body-file = `b"django depth\n"`; `inject-pack --name django --body-file … --in-place` | exit `EXIT_OK`; reparse the rewritten file → region ids `["CORE","PACK:django","PROJECT"]`; `region_sha(PACK:django) == region_sha(b"django depth\n")` (the §2.6 identity) |
| `test_inject_pack_stdout_default` | as above without `--in-place` | exit `EXIT_OK`; stdout bytes parse to the 3 regions; the on-disk staged file is **unchanged** (stdout-only) |
| `test_inject_pack_alpha_order_with_existing` | staged CORE+PROJECT; inject `--name flask`, then on the result inject `--name apache` | final region order is `CORE, PACK:apache, PACK:flask, PROJECT` — alpha between CORE and PROJECT regardless of injection order (proves `compose` re-sorts) |
| `test_inject_pack_duplicate_rejected` | staged file that already has `PACK:django`; inject `--name django` again | exit `EXIT_INVALID`; stderr contains `E_DUP_PACK` (the ADR-named rejection). NB this is a *hand-built* double-inject — the installer never does this (N1, §1.3); the test guards the verb, not an installer path |
| `test_inject_pack_idempotent_fixedpoint` | inject `--name django` into CORE+PROJECT → out1; run `regions.py compose` on out1 → out2 | `out2 == out1` (compose of the injected result is a fixed point — round-trip stable, the §2.6/§2.5 identity) |
| `test_inject_pack_invalid_slug` | `--name "Django!"` | exit `EXIT_INVALID`; stderr names the slug grammar |
| `test_inject_pack_missing_body_file` | `--body-file /nonexistent` | exit `EXIT_USAGE`; stderr `file not found` |
| `test_inject_pack_literal_marker_in_body` | body-file containing a column-0 `<!-- HOS:CORE:START -->` line | exit `EXIT_INVALID`; assert **membership** — `E_LITERAL_MARKER_IN_BODY` is **among** the emitted error codes, NOT that it is the sole/equal error (N3). A column-0 literal marker in the injected body trips `E_LITERAL_MARKER_IN_BODY` **and** structural codes (`E_NESTED`/`E_UNBALANCED`) because the smuggled `:START` opens a region the body never closes; the test asserts the literal-marker code is present, not that it is the only one |

(The "idempotent compose fixed-point of the result" the prompt names is `test_inject_pack_idempotent_fixedpoint`.)

### 5.2 Install-path — new `tests/framework/test_pack_install.py`

A subprocess harness that runs `bootstrap/hos_install.sh --local --dry-run`/real against a throwaway `git init` target with a fixture `packs/` tree, asserting on composed output + manifest + warnings/exit. Build a minimal fixture pack under the test's tmp HOS source (or point `--local` at a staged copy with `packs/django/security-reviewer.md`). Match the existing subprocess style (`subprocess.run([... "bash", install_sh, ...], capture_output=True)`).

| Test | Invocation | Assert |
|---|---|---|
| `test_install_with_pack_composes_three_regions` | `--pack django` (django deepens `security-reviewer`) | `.claude/agents/security-reviewer.md` has region ids `["CORE","PACK:django","PROJECT"]`; an agent django does NOT deepen has `["CORE","PROJECT"]` only |
| `test_install_pack_manifest_rows` | `--pack django` | `.hos-manifest` contains `.claude/agents/security-reviewer.md\tPACK:django\t<sha>` row, and the sha equals `region_sha` of the composed PACK body |
| `test_install_pack_records_config` | `--pack django` | `scripts/framework/config.sh` contains `PACK="django"` |
| `test_install_no_pack_core_only_warn` | `--no-pack` | exit 0; agents are CORE+PROJECT only (no PACK row in manifest); stderr/stdout contains the #237 bare-core WARN |
| `test_install_no_pack_interactive_errors` | no `--pack`, no `--no-pack`, stdin a tty (simulate interactive) | non-zero exit; message names `--pack`/`--no-pack` (S1 hard default) |
| `test_install_unknown_pack_hard_error` | `--pack nope` (no `packs/nope/`) | non-zero exit; message `unknown pack 'nope'`; **nothing written** to `.claude/agents` (assert the target agents dir is unchanged/empty) |
| `test_install_multipack_warns` | `--pack a --pack b` (both exist) | exit 0; multi-pack WARN fires once; composed agent has both PACK regions in alpha order |
| `test_install_pack_mutual_exclusion` | `--pack django --no-pack` | usage error exit 1 before any work |
| `test_upgrade_pack_version_bump_refresh` | install `--pack django`, bump the fixture `packs/django/security-reviewer.md` body, re-install (config-resolved pack) | the PACK region is REFRESHed (new body on disk); manifest `base_sha` re-stamped; exit 0 |
| `test_upgrade_consumer_edited_pack_hardstop` | install `--pack django`, hand-edit the on-disk `PACK:django` region, bump the fixture body, re-install | drift hard-stop: non-zero (`exit 4`), drift report names `PACK:django`, **nothing written / no version stamp** |
| `test_pack_switch_drops_old_region` | install `--pack flask` (unedited flask region), then `--pack django` | `PACK:flask` is DROPped (gone from file + manifest), `PACK:django` introduced; exit 0; `config.sh PACK="django"`. **Prior install must be cleanly completed (N2)** so `.hos-manifest` carries the `PACK:flask` row the sweep keys on |
| `test_install_no_pack_over_recorded_pack_drops_region` (B1) | install `--pack django` (clean), then re-install `--no-pack` (no `--pack` flag, config still records `PACK="django"`) | `--no-pack` **wins** over the recorded `PACK=django` (R1 gate): `PACK:django` is STRIPped (gone from `security-reviewer.md` + manifest → agent is CORE+PROJECT only); `config.sh` `PACK=` is **cleared** (R2a — no `PACK=` line, or blank); #237 bare-core WARN fires; exit 0. Guards against the silent-no-op (`--no-pack` must not be ignored when `config.sh PACK=` is set) |
| `test_install_inject_failure_writes_nothing` (B2) | seed a **malformed** `packs/django/security-reviewer.md` (e.g. a column-0 literal marker → inject-pack non-zero), then install `--pack django` | install exits **non-zero** (the pre-Phase-B abort gate, exit 4) **AND** the target `.claude/agents/` is **unchanged** (no agent written — assert the dir is empty/absent on a first install, or byte-identical to pre-state on a re-install) **AND** `.hos-manifest` is **not written** (no partial manifest) **AND** `.hos-release` is **not stamped**. Proves the install is fail-closed, not just that the one bad agent is skipped |

Tests that require a real upgrade (version bump, consumer-edit, switch) need a writable HOS source so the fixture body can be mutated between installs — copy the relevant slice (regions.py + one agent template + a fixture `packs/`) into a tmp HOS source, or use `--local` against a tmp clone. Where a full installer run is too heavy, the **switch/REFRESH/HARDSTOP merge behavior is already unit-covered** by `test_plan_upgrade.py`'s DROP/REFRESH/HARDSTOP scenarios (the install-path tests then only need to assert the *wiring* reaches those, e.g. that the old pack region is absent from the staged template on a switch).

---

## 6. Flags for the coder (ADR-silent points + sub-decisions made)

All sub-decisions below were made and applied above; none reopen an ADR-031 decision. None is a genuine architecture gap — each is a within-mechanism choice the ADR left to the design.

1. **§1.6 slug validation inside `inject-pack`** — ADR shows the verb's construction but not slug validation. **Decided:** validate with `re.fullmatch(_PACK_SLUG, name)` (step 2), fail-closed `EXIT_INVALID`. Cannot change valid-input behavior. CONFIDENCE: high.
2. **§2.3 `config.sh` overwrite mechanic** — ADR says "overwrite-if-`--pack`-differs" but the existing idiom only appends. **Decided:** `perl -i -pe 's|^PACK=.*|PACK="<name>"|'` (the installer's own engine, no new dep) for the overwrite case; reuse the L511–515 append idiom for absent/create. Multi-pack-from-flags is **not** recorded (single-value `PACK=` is all v0.3.0 wires). CONFIDENCE: high.
3. **§3.1 `packs/` not added to `REQUIRED_SOURCE_PATHS`** — keeping `--no-pack` installs valid against a core-only release; the R3 unknown-pack check fails closed instead. CONFIDENCE: high.
4. **§3.3 `pack.toml` name/dir mismatch severity** — ADR says "sanity-check" without severity. **Decided + CONFIRMED by the architect (round 2):** **WARN** at consumer install time (directory name authoritative), not a hard error — with one refinement applied: the WARN now names **both** remedies ("rename the directory or correct `name=`"), and the mismatch is a **HARD failure in the hos-dev CI lint** for pack *authors* (§3.5) — the author-vs-consumer severity split. Consumers are never blocked by a stale `pack.toml`; authors can never ship one. CONFIDENCE: high (architect-confirmed).
5. **§3.5 lint input path** — pipe `inject-pack` stdout to `validate /dev/stdin --placeholder-keys …`; the lint reuses the existing D7 path with no regions.py change. CONFIDENCE: high.
6. **Pre-existing latent bug (flagged, NOT fixed in this design) — A4 `_plan_rc != 0` half-write.** The existing `_plan_rc != 0` path (hos_install.sh L771–773) does `fail; continue` with no sentinel and falls through the decide-all-then-act gate into Phase B — the **same** half-write defect as B2, and it **predates** this design (it is not introduced by the pack mechanism). B2's installer fix (§2.4.1) is the natural place to route this path through the **one** pre-Phase-B abort gate (set the sentinel on the A4 `fail;continue` too), but the A4 bug itself should be tracked as a **separate issue** against the pre-existing installer — this design only ensures the new inject path does not add a *second* instance of the defect and routes both through one gate. No fix is designed here for the A4 path's other failure modes.

No genuine architecture gap was hit — ADR-031 Decisions 1–5 + the deltas fully determine the mechanism. The five points above are mechanism sub-decisions, made here, ready for the coder.

---

## Human Review Required

RISK: MEDIUM
CONFIDENCE: high

**Change classification:** additive — this is a new companion design document detailing an already-ACCEPTED ADR; it adds one CLI verb contract and installer-wiring steps, introduces no new architectural decision, and reuses the existing region/merge/manifest machinery unchanged. It is not `structural` (no change to the region model, merge, schema, or Phase A/B) and is more than `clarifying` (it specifies a new verb + new installer control flow), so: **additive**.

Why MEDIUM (not LOW): the design wires a new install-time control path (pack resolution, no-pack decision tree, `config.sh` recording, A1 staging change) whose error/exit semantics are load-bearing for fail-closed behavior (unknown-pack hard error, interactive/CI no-pack error, drift on switch). Why CONFIDENCE high: every mechanism reuses existing, tested code (`compose`, `validate`, `merge_region`, `plan_upgrade`, the append idiom, `perl -i` substitution); the one new verb is ~15 lines of glue over pure functions; the five sub-decisions are within-mechanism and reversible.

Reviewer attention requested on: (a) §2.2 R1/R2a — the `! $NO_PACK` gate on the config read + the R2a `config.sh PACK=` clear (B1: `--no-pack` must win over a recorded `PACK=` and not silently re-add it next run); (b) §2.4.1 — the pre-Phase-B abort gate (B2: inject failure must write **nothing**, reusing the one decide-all-then-act gate, not a second exit path) and the routing of the pre-existing A4 `_plan_rc != 0` half-write through it; (c) §4.2 — the django→none STRIP semantics added alongside the SWITCH; (d) §2.3 R5 the `perl -i` overwrite of `config.sh PACK=` (correct anchor, no clobber of other keys).

**Round-2 revision (architect loop, round 2 of 5):** applied the architect's two BLOCKING fixes (B1 silent-`--no-pack`, B2 half-write/false-fail-closed) and three non-blocking clarifications (N1 idempotent re-install, N2 clean-prior-manifest precondition, N3 membership assertion); recorded the architect's CONFIRMED §6 flag #4 (WARN + author-vs-consumer split) and flagged the pre-existing A4 half-write as a separate issue. Two new tests added (`test_install_no_pack_over_recorded_pack_drops_region`, `test_install_inject_failure_writes_nothing`).
