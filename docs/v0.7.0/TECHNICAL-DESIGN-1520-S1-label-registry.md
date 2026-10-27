# TECHNICAL DESIGN — #1520 S1: label registry kind, `check`/`provision` tool, conformance test, `KNOWN_LABELS` fix

Status: **APPROVED_WITH_CHANGES — architect, round 1, 2026-10-20** (§18). The architect's edits are inline and marked "(architect R1)". Hand to `coder`. Every architect edit and ruling in §18 is binding.
Binds to: `docs/v0.7.0/ADR-1520-pending-actor-label-migration.md` (ACCEPTED FOR DESIGN), AD-7, AD-8, AD-12, and slice row S1 (§3).
Verified against: `c48c8ddd0` (`HEAD` of `worker-1520-s1-td-label-registry-*`, which equals `origin/main` plus nothing).
Change class: **additive**. S1 adds new files and one row each to two existing tables. It does not change the control flow of any existing path and it mutates no GitHub state. The only edit to an existing behavior is the `KNOWN_LABELS` spelling fix, and that check still exits 0 on today's tree (§9).

RISK: MEDIUM. S1 adds a new GitHub **write** surface (label creation) behind a token-minting L3 wrapper, and new protected surfaces (`contract/**`, `bootstrap/**`, `scripts/framework/**`). S1 never runs that surface; H-1 is the first run.
CONFIDENCE: HIGH on the registry, loader, CLI and wrapper contracts. All of them reuse landed patterns, cited below. MEDIUM on the P1 pattern set (§8.3). It is heuristic by nature. I measured it against today's tree (§8.3, "Measured result"), and P6 backstops it.

## Human Review Required
- **CODEOWNERS gate.** S1 touches `contract/**`, `bootstrap/**` and `scripts/framework/**`. It needs the human approval gate, as every S1 PR does (ADR §3, "Prot.").
- **New write tool, not run in S1.** `bootstrap/provision_labels.sh provision --apply` creates labels in a GitHub repo. S1 ships it but never invokes it. Its first use is H-1, which is a human act (§7.4).
- **TD-ESC-1** asked the architect to confirm that this wrapper mints its own token. **Ruled (§18.2):** yes, under the `pr_review.sh` precedent, with one added binding condition: scrub the inherited credentials before the mint (§7.1 step 3a).

---

## 0. Inputs and search-first record

Read in full: ADR-1520 (all 590 lines); `docs/LABELS.md`; `scripts/automation/lib/dimension_registry.py`; `bootstrap/hos_install.sh:2120-2212` (registry-data block); `scripts/framework/check_agents_static.sh:150-195`; `tests/oversight/test_agents_static_logic.py:1-140`; `tests/framework/test_install_registry_data.py` (T5.44); `tests/automation/test_dimension_registry.py:720-870` (T5.43, T5.45 seam); ADR-1643 AD-1/AD-1a and §10.4.

**What already exists, which S1 reuses rather than re-implements** (searched `scripts/` recursively, `bootstrap/`, `bin/`, `scripts/automation/lib/*.py`):

| Need | Existing code | Used how |
|---|---|---|
| Registry engine | `scripts/automation/lib/dimension_registry.py` `load_registry`, `KINDS`, `RegistryError`, `LayerDoc`, `LoadContext`, `_path_escapes` | One new `KINDS` row and one handler module (ADR VF-8, AD-7). |
| GitHub REST with retry, backoff and timeouts | `scripts/automation/lib/github.py` `_run_gh(args, retries=, stdin_json=)` (30 s per call; 404 returns `None`; other non-2xx raises `GitHubError(status_code=)`) | Every GitHub call in `labels_cli.py`. Private-name import precedent: `probe.py:37`, `stale_commit_detector.py:27`. There is no public list-labels or create-label helper, and S1 does not add one to `github.py` (file cap; see §13). |
| Token mint and revoke | `bootstrap/get_app_token.sh --app <role>` (sourced temp file); `bootstrap/revoke_app_token.sh` (reads `GH_TOKEN` from env, idempotent, always exits 0) | The L3 wrapper uses `bootstrap/pr_review.sh:131-252`'s exact shape (§7). |
| Token-bearing L3 over an L2 CLI | `bootstrap/pr_review.sh` (the most complete: signal traps, revoke-once guard, mint-failed env flag), `bootstrap/merge_authority.sh` | Template for `provision_labels.sh`. |
| Interpreter ladder for an L2 that needs non-stdlib (PyYAML) | `bootstrap/invoke_agent.sh` (venv python first, then `python3`) | Copied into the wrapper (AD-1a's stdlib caveat: `labels_cli.py` needs PyYAML through the loader). |
| Audit record writer | `scripts/oversight/lib/audit_log.py` `write_event(event, root=)`, loaded by file path as `scripts/automation/dimension_sweep_cli.py:188-197` does | `labels-checked` and `labels-provisioned` records. |
| Glob matcher with protected-surface semantics | `scripts/framework/require_human_approval.py` `glob_to_regex` (`dir/**`, `*` = one segment, plain path = exact) | Allowlist `[historical]` globs in the conformance test. |
| CLI usage-error idiom (argparse that raises instead of exiting) | `scripts/automation/dimension_registry_cli.py:51-67` `_Parser.error` | Copied into `labels_cli.py`. |
| Label provisioning or label-literal conformance | **None.** I searched for `gh label`, `label create`, repo-level `POST …/labels` and `labels` conformance tests, and found nothing (this agrees with ADR VF-7). | New in S1. |

---

## 1. Current state (grounded)

- `dimension_registry.KINDS` has one row, `hos.dimension-registry` (`:102-121`). The engine requires `<directory>/core.yaml`. It reads the pack set from `contract/resolved-packs.txt` (present in this repo, intentionally empty). It allows only `core.yaml`, `project.yaml`, `project.yaml.template` and `pack-<slug>.yaml` in the directory (`:374-388`). It parses each layer with a duplicate-key-rejecting SafeLoader. It then calls `handler.resolve(docs, ctx)` once and turns any non-`RegistryError` into `kind_handler_failed` (`:412-419`).
- `tests/automation/test_dimension_registry.py:737` (T5.43) asserts `dr.registered_schemas() == (SCHEMA,)`. **A second `KINDS` row breaks this assertion.** The ADR's S1 file list does not name this file, so S1 adds it (§2, §15).
- `bootstrap/hos_install.sh:2146` is `_REGISTRY_KINDS=( "dimensions.yaml:contract/dimensions" )`. The loop **only** copies or prunes `pack-<slug>.yaml` files. `contract/dimensions/core.yaml` reaches consumers through `scripts/framework/framework_consumer_files.txt:102`, not through this row. T5.44 (`test_install_registry_data.py:159-166`) compares the row set with `{(k.pack_source, k.directory) for k in KINDS.values()}`, so it follows a new row automatically and needs no edit.
- `check_agents_static.sh:170` has `KNOWN_LABELS="needs-human|needs-ai|needs-coordination|…"`. `needs-coordination` is a misspelling of `hos-coordination` (`docs/LABELS.md:45`). Nothing in `.claude/agents/` uses either token as an escalation target, and the script exits 0 on today's tree (measured).
- `tests/oversight/test_agents_static_logic.py:83-87` keeps its own copy of the `KNOWN_LABELS` string (`_LABELS`). It includes `needs-coordination`.
- `docs/LABELS.md`'s table is **broken in two**. The section "The `needs-ai` authorizing act" (`:32-41`) sits between the `needs-human` row and the `hos-halt` row, so rows `:42-49` render as plain text with no table header. P2 needs one contiguous table (§10).
- `docs/LABELS.md` has stale citations: `merge_authority.py:633`/`:1223` are now `:634`/`:1268` (VF-11), and `check_agents_static.sh:158` is now `:170`.
- `git grep -l needs-ai` returns 125 tracked files: VF-1's 124 plus ADR-1520 itself. 38 of them lie outside the `[historical]` globs. That is exactly VF-1's 9 + 6 + 9 + 14 (§8.5).

---

## 2. File list (14 files; cap 15; 1 slot of slack)

| # | File | New/edit | What |
|---|---|---|---|
| 1 | `contract/labels/core.yaml` | new | Registry data (§3). |
| 2 | `scripts/automation/lib/label_registry.py` | new | Label-kind handler and public loader API (§4). |
| 3 | `scripts/automation/lib/dimension_registry.py` | edit | One `KINDS` row, the `LABELS_SCHEMA` constant, and one docstring sentence (§4.1). **Nothing else.** |
| 4 | `bootstrap/hos_install.sh` | edit | One `_REGISTRY_KINDS` row (§5). **Nothing else.** |
| 5 | `scripts/framework/labels_cli.py` | new | L2: `check`, `provision` (§6). |
| 6 | `bootstrap/provision_labels.sh` | new | L3 wrapper (§7). Mode `0755`. |
| 7 | `scripts/framework/label_literal_allowlist.txt` | new | P4 data (§8.5). |
| 8 | `tests/framework/test_labels_cli.py` | new | Loader (LR-\*), CLI (LC-\*/LP-\*) and wrapper (LW-\*) tests (§12). |
| 9 | `tests/framework/test_label_conformance.py` | new | P1–P6 and C-\* (§8, §12). |
| 10 | `docs/LABELS.md` | edit | Repair the table; add rows; fix citations; replace "Known gaps" (§10). |
| 11 | `scripts/framework/check_agents_static.sh` | edit | `KNOWN_LABELS` value only (§9). |
| 12 | `tests/oversight/test_agents_static_logic.py` | edit | `_LABELS` and three classification tests (§9). |
| 13 | `tests/automation/test_dimension_registry.py` | edit | **Not in the ADR list (§15).** One line at `:737`: the expected tuple becomes `(dr.DIMENSIONS_SCHEMA, dr.LABELS_SCHEMA)`. |
| 14 | `SCRIPTS-INDEX.md` | regenerated | `bash scripts/framework/gen_scripts_index.sh`. Never hand-edited. |

**Not touched** (and the reason):
- `tests/framework/test_install_registry_data.py`: T5.44 follows the table (§1).
- `scripts/framework/framework_consumer_files.txt` and `.gitattributes` lines: the consumer path is S6b's (§13, TD-ESC-2).
- `CLAUDE.md`'s canonical-entry-point table: that is S5's file, and it is in `[pending]`.
- `contract/OVERSIGHT-CONTRACT.md` event rows: S5 adds them (ADR §3, S5 row).
- `scripts/automation/lib/github.py`: §13.

---

## 3. Registry data: `contract/labels/core.yaml`

### 3.1 Schema (closed grammar; every unknown key is an error)

```yaml
schema: hos.label-registry       # required, exact
schema_version: 1                # required, int 1 (bool rejected by the engine)
owner: core                      # required, exact
labels:                          # required, non-empty list
  - name: <str>                  # required. ^[a-z0-9][a-z0-9:._-]*$, 1..50 chars (GitHub's name limit)
    status: <str>                # required. one of: active | planned | legacy-read | retired
    color: "<str>"               # required. ^[0-9a-f]{6}$, a STRING (quote it: YAML reads 000000 as int)
    description: <str>           # required. 1..100 chars (GitHub limit), no "\n" or "\r"
    writers: [<repo path>, ...]  # optional, default []. Normal-form repo-relative paths
    readers: [<repo path>, ...]  # optional, default []. Same rules
    provision: <bool>            # optional, default true. false = provision never creates it
families: []                     # optional, default []. List of {prefix, provider} (§4.4)
```

A layer file may contain no other top-level key. That rule is the engine's (`top_level_keys`, §4.1).

### 3.2 Seed entries (exactly these 20, in this order)

The names come from three sources: the `docs/LABELS.md` table, today's P1 scan of live code (§8.3, measured), and the two `planned` names. Each `writers`/`readers` path below was checked to contain the literal (P3). If P3 fails on any declared path, the coder **removes that path from the declaration**. The coder never adds a literal to a source file to satisfy P3.

| name | status | color | provision | writers | readers | description |
|---|---|---|---|---|---|---|
| `needs-ai` | active | `1d76db` | true | `.github/workflows/label-swap.yml`, `bin/hos-cron`, `scripts/automation/lib/merge_authority.py`, `scripts/automation/lib/self_review_source.py` | `scripts/framework/select_work_candidates.py`, `scripts/automation/lib/probe.py`, `bin/hos-cron` | Legacy pending-actor label (worker's court). Being replaced by needs-worker, see #1520. |
| `needs-worker` | planned | `1d76db` | true | — | — | Pending actor: the worker must act. Replaces needs-ai (#1520). |
| `needs-overseer` | planned | `5319e7` | true | — | — | Pending actor: the overseer must act (#1520). |
| `needs-human` | active | `d93f0b` | true | `.github/workflows/label-swap.yml`, `bin/hos-cron`, `bootstrap/escalate_to_human.sh`, `bootstrap/hos_install.sh`, `scripts/automation/lib/merge_authority.py` | `scripts/automation/lib/merge_authority.py`, `scripts/automation/lib/triage.py`, `scripts/framework/select_work_candidates.py`, `bin/hos-cron` | A human must act. Blocks merge and autonomous work selection. |
| `hos-halt` | active | `b60205` | **false** | — | `scripts/automation/lib/merge_authority.py`, `bin/hos-cron` | Halts every HOS cron cycle while any open issue carries it. Never create it (the kill switch is a file). |
| `hos-claimed` | active | `c5def5` | true | `scripts/automation/lib/claim.py` | — | Claimed by an HOS autonomous cycle. |
| `hos-embargo` | active | `b60205` | true | `scripts/automation/lib/merge_authority.py` | — | Security report under embargo. Human handling only. |
| `hos-coordination` | active | `0e8a16` | true | `scripts/automation/lib/self_review_source.py` | `scripts/automation/lib/probe.py` | HOS coordination item (self-review finding or cross-role work). |
| `hos-budget-gated` | active | `fbca04` | true | `.claude/agents/worker.md` | — | Deferred by the HOS budget gate. |
| `hos-in-progress` | planned | `ededed` | **false** | — | — | Spec-stage only (UNATTENDED-WORKER-TECH-DESIGN). Not implemented. |
| `hos-autowork-authorized` | planned | `ededed` | **false** | — | — | Spec-stage only (UNATTENDED-WORKER-TECH-DESIGN). Not implemented. |
| `suppression-expired` | planned | `ededed` | **false** | — | — | Spec-stage only (UNATTENDED-WORKER-PROTOCOL). Not implemented. |
| `release-request` | active | `0052cc` | true | — | `bin/hos-cron`, `bootstrap/escalate_to_human.sh` | Requests a release. Starts the NG3b release-authorization protocol. |
| `release-authorized` | active | `0e8a16` | true | — | `.claude/agents/worker.md` | NG3b release authorization signal. Apply by hand only. |
| `priority:critical` | active | `b60205` | true | `bin/hos-cron`, `.claude/agents/worker.md` | — | Work-selection ordering: critical. |
| `priority:high` | active | `d93f0b` | true | `.claude/agents/worker.md` | — | Work-selection ordering: high. |
| `priority:medium` | active | `fbca04` | true | `.claude/agents/worker.md` | — | Work-selection ordering: medium. |
| `priority:low` | active | `c2e0c6` | true | `.claude/agents/worker.md` | — | Work-selection ordering: low (the default when unlabeled). |
| `wontfix` | active | `ffffff` | true | `.github/workflows/label-swap.yml` | `scripts/automation/lib/triage.py` | This will not be worked on |
| `design-concern` | active | `d4c5f9` | true | `scripts/review_self.sh` | `scripts/oversight/validators/issue_query.py` | Design concern raised by an HOS self-review. |

`families: []`.

Notes the coder must keep:
- `wontfix` uses GitHub's default color and description, verbatim, so a repo with the default label reports clean.
- `priority:*` readers are empty on purpose. `select_work_candidates.py` builds the names with `f"priority:{name}"` (`:129`), so the literal is not in that file and P3 would fail. `docs/LABELS.md` documents the reader in prose.
- Why the three spec-stage names are `planned` with `provision: false`: they are in `docs/LABELS.md`'s table (P2) and, for one of them, in `KNOWN_LABELS` (P1). But no code implements them. Creating them in a repo would make them look live, which `docs/LABELS.md:47` says they are not.
- `hos-halt` is `active` because code honours it (`merge_authority.py:495`, `bin/hos-cron:1041`). It is `provision: false` because the spec forbids creating it (ADR AD-7, `docs/LABELS.md:42`).
- `needs-worker` and `needs-overseer` are `planned` and provisionable. H-1 creates them (ADR S1 row).

---

## 4. Loader: `scripts/automation/lib/label_registry.py` (L1, pure)

### 4.1 Edits to `dimension_registry.py` (exactly these)

1. After `DIMENSIONS_SCHEMA`, add `LABELS_SCHEMA = "hos.label-registry"`. It lives here, not in the handler, so `KINDS` needs no import of the handler. That avoids a circular import, because the handler imports the engine.
2. Add a second `KINDS` entry:
   ```
   LABELS_SCHEMA: KindSpec(
       schema=LABELS_SCHEMA, schema_version=1, directory="contract/labels",
       pack_source="labels.yaml",
       handler_module="scripts.automation.lib.label_registry",
       top_level_keys={
           "core":    frozenset({"schema", "schema_version", "owner", "labels", "families"}),
           "pack":    frozenset({"schema", "schema_version", "owner", "pack"}),
           "project": frozenset({"schema", "schema_version", "owner"}),
       },
       core_only_keys=frozenset({"labels", "families"}),
       project_only_keys=frozenset(),
   )
   ```
3. In the module docstring, replace "The dimensions kind is the only kind registered here; its handler lives in this module (TD-D25)." with: "The dimensions kind's handler lives in this module (TD-D25). The label kind's handler is `label_registry.py` (ADR-1520 AD-7)."

The engine is unchanged. Because of `core_only_keys`, a pack or project file carrying `labels`/`families` already fails with `core_only_key`. The handler adds a stricter rule (LR-0): any non-core layer fails, even one with only a header.

### 4.2 Public API

```
LABELS_SCHEMA: str                       # re-exported from dimension_registry
STATUSES: tuple[str, ...] = ("active", "planned", "legacy-read", "retired")
PROVISIONABLE_STATUSES: frozenset[str] = {"active", "planned", "legacy-read"}

@dataclass(frozen=True)
class LabelSpec:
    name: str; status: str; color: str; description: str
    writers: tuple[str, ...]; readers: tuple[str, ...]
    provision: bool
    family: str | None          # the family prefix for provider-supplied labels, else None
    source: str                 # "contract/labels/core.yaml" or "family:<prefix>"

@dataclass(frozen=True)
class Family:
    prefix: str; provider: str; source: str

@dataclass(frozen=True)
class ResolvedLabels:
    schema: str
    labels: Mapping[str, LabelSpec]      # key = name; static + family-expanded; MappingProxyType
    families: tuple[Family, ...]         # sorted by prefix
    source_files: tuple[str, ...]
    digest: str                          # sha256 of canonical JSON of everything else

def resolve(docs: tuple[LayerDoc, ...], ctx: LoadContext) -> ResolvedLabels   # engine hook
def to_json(reg: ResolvedLabels) -> dict                                      # engine hook
def load(repo_root: str | Path, *, packs: Sequence[str] | None = None) -> ResolvedLabels
    # exactly dimension_registry.load_registry(repo_root, LABELS_SCHEMA, packs=packs)
def provisionable(reg: ResolvedLabels) -> tuple[LabelSpec, ...]
    # status in PROVISIONABLE_STATUSES and provision is True; sorted by name
def family_for(reg: ResolvedLabels, literal: str) -> Family | None
    # the family whose prefix the literal starts with, else None
```

Purity, as in the engine: no argparse, no `os.environ`, no network, no subprocess, no file writes. The handler imports nothing outside the stdlib and `scripts.automation.lib.dimension_registry`. PyYAML stays the engine's lazy import, so a missing PyYAML is still `yaml_unavailable`.

### 4.3 `resolve` rules, in this fixed order (first failure wins; every failure is one `RegistryError`)

| Rule | Check | Code |
|---|---|---|
| LR-0 | Every doc has `owner == "core"` (label names are fixed literals, ADR AD-7) | `core_only` |
| LR-1 | `labels` is a non-empty list | `core_empty` (absent or `[]`), `unknown_item_key` (not a list) |
| LR-2 | Each item is a mapping. Keys ⊆ {name, status, color, description, writers, readers, provision}. name, status, color and description are present. name, status and description are `str`. **The type of `color` is LR-6's to judge, not LR-2's (architect R1).** Otherwise LR-2 would claim the `000000` YAML-int case that LR-2's test expects as `bad_color` | `unknown_item_key` |
| LR-3 | `name` matches `^[a-z0-9][a-z0-9:._-]*$` and has length ≤ 50 | `bad_label_name` |
| LR-4 | No two names are equal under `str.casefold()` (GitHub names are case-insensitive) | `duplicate_id` |
| LR-5 | `status` ∈ `STATUSES` | `bad_status` |
| LR-6 | `color` is a `str` matching `^[0-9a-f]{6}$` | `bad_color` |
| LR-7 | `description` is 1..100 chars with no `\n` or `\r` | `bad_description` |
| LR-8 | `writers`/`readers`, if present, are lists of non-empty `str`. Each is normal-form (`PurePosixPath(p).as_posix() == p`, no `.` segment) with no duplicates within its list. Each passes `dimension_registry._path_escapes(root, p) is None` | `unknown_item_key` (shape), `path_escape` |
| LR-9 | `provision`, if present, is a `bool` | `unknown_item_key` |
| LR-10 | `families`, if present, is a list. Each item has exactly the keys {prefix, provider}, both `str`. `prefix` matches `^[a-z0-9][a-z0-9-]*:$`. `provider` matches `^scripts\.automation\.lib\.[a-z_][a-z0-9_]*:[a-z_][a-z0-9_]*$`. No prefix equals another (second-review R1: the former "or is a prefix of another" clause was removed as unreachable, because the grammar allows `:` only as the last character, so no valid prefix can start another) | `bad_family` |
| LR-11 | No static `name` starts with any family prefix | `family_collision` |
| LR-12 | For each family in prefix order: import the module, get the attribute, and call `provider(ctx)`. It must return a `list`/`tuple` of mappings. Each mapping passes LR-2..LR-9 under the same codes, and its name starts with the family's prefix. Any exception other than `RegistryError` becomes `family_provider_failed` | `family_provider_failed` |
| LR-13 | No family-supplied name casefold-equals any static name or another family's name | `duplicate_id` |

**Evaluation order, made exact (architect R1).** LR-0 and LR-1 run first. Then the per-item rules (LR-2, LR-3, LR-5, LR-6, LR-7, LR-8, LR-9) run item by item, in list order. Each item runs all of them before the next item starts. LR-4 runs once, after every item has passed. LR-10 to LR-13 follow, in that order. Every LR-2 test fixture holds exactly one defect, so this order decides no test. It exists so that two coders produce the same first error.

**Why the provider path is restricted:** `core.yaml` is CORE-only and protected, but it is still data that names code to import. LR-10 confines it to first-party `scripts.automation.lib.*`, so the most a registry edit can do is call a reviewed module function. T3.1's `stage` provider is expected there (ADR AD-7).

**Provider contract** (for T3.1): `def <fn>(ctx: LoadContext) -> Sequence[Mapping[str, object]]`. It is pure. It may read files under `ctx.repo_root`, for example by calling `load_registry` for `contract/stages`. It returns label items in the §3.1 item grammar.

### 4.4 Digest and JSON

`to_json` returns:

```
{schema, source_files, families: [{prefix, provider, source}…], labels: [{name, status, color, description, writers, readers, provision, family, source}…], digest}
```

The lists are sorted (labels by name, families by prefix). `digest` is `sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False))` over everything except `digest`, which is the same construction as `dimension_registry._canonical`.

---

## 5. Installer: one row

`bootstrap/hos_install.sh:2146` becomes:

```
_REGISTRY_KINDS=( "dimensions.yaml:contract/dimensions" "labels.yaml:contract/labels" )
```

It stays on one line, because T5.44's regex is single-line. Nothing else in the installer changes. **Effect in S1:**
- No pack ships `labels.yaml`, so the copy step is a no-op.
- The prune step globs `contract/labels/pack-*.yaml` in the target, finds nothing, and continues (`[[ -e ]] || continue`).

**This row does not ship `contract/labels/core.yaml`** (§1). Shipping it is S6b's job (TD-ESC-2).

---

## 6. L2: `scripts/framework/labels_cli.py`

### 6.1 Surface

```
labels_cli.py check     --app <worker|overseer|human> [--repo <owner/name>]
labels_cli.py provision --app <worker|overseer|human> [--repo <owner/name>] [--apply]
```

- `--app` is required, a closed enum, and accepts the `--app=x` form. L2 uses it **only** to record identity in the audit record. The token is minted by L3 (§7).
- `--repo` is optional. Its default is parsed from `git -C <repo_root> remote get-url origin`: strip `git@github.com:`, `https://github.com/` and a trailing `.git`. Both explicit and parsed values must match `^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$`.
- `--apply` is valid only on `provision`. Without it, `provision` is a dry run.
- There are no other flags and no `migrate` (S6a). Unknown subcommands or flags are usage errors.
- **The grammar must match the wrapper's extraction exactly (architect R1).** L3 decides whether to mint, and for which role, by reading `$1` and `--app` (§7.1 step 2). L2 must accept nothing that L3 would read differently:
  - The subcommand is `argv[0]`. `--app`, `--repo` and `--apply` are defined on the **subparsers only**, never on the top-level parser. `--app worker check` is therefore a usage error.
  - Every parser, including each subparser (through `parser_class=_Parser`), sets `allow_abbrev=False`. `--ap worker` is a usage error.
  - A repeated `--app` is a usage error, whichever of the `--app x` and `--app=x` forms is used. Detect it with a custom action or a count. Do not rely on argparse's default, which is last-wins.
  - The `--repo` value additionally fails if either segment is `.` or `..`. The regex alone admits `../..`, which would put a path traversal into the `repos/{o}/{r}/…` endpoint.
- Import bootstrap: follow `scripts/automation/dimension_registry_cli.py:33-38`. Insert the repo root into `sys.path` only if it is absent, then do `from scripts.automation.lib import …`. That is not I/O, and the no-I/O-on-import rule still holds.

Module skeleton (seams for tests; the names are binding):

```
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
LABEL_PAGE_BOUND = 10           # pages of per_page=100 => 1000 labels
def main(argv: Sequence[str] | None = None, *, repo_root: Path | None = None,
         env: Mapping[str, str] | None = None) -> int
def _gh(args: list[str], *, retries: int, stdin_json: dict | None = None) -> Any
    # the ONLY GitHub call site: returns github._run_gh(args, retries=retries, stdin_json=stdin_json)
def _origin_url(repo_root: Path) -> str | None      # git remote get-url origin; None on failure (timeout 30 s)
def _audit_write(event: dict, repo_root: Path) -> str  # audit_log.write_event loaded by file path
def _now_iso() -> str                                # UTC, "YYYY-MM-DDTHH:MM:SSZ"
```

`if __name__ == "__main__": sys.exit(main())`. Importing the module performs no I/O. The module may contain **no label-name literal** (C-10).

### 6.2 Preconditions (in order; each failure exits 2 with **zero** GitHub calls)

1. Parse argv → `usage` on failure.
2. `env.get("HOS_LABELS_TOKEN_MINT_FAILED") == "1"` → `token_mint_failed`.
3. `env.get("GH_TOKEN")` is empty or absent → `no_token`. There is deliberately no fallback to ambient `gh` auth, which would act under a personal login.
4. Resolve `--repo` → `repo_unresolved` if the default cannot be parsed or a value fails the regex. **The error message never contains the raw `origin` URL (architect R1).** A remote URL can carry an embedded credential. Name the failure, for example "origin remote is not a github.com owner/name URL", and do not echo the value.
5. `label_registry.load(repo_root)` → `registry:<RegistryError.code>`, with the message and path.

### 6.3 Listing repo labels (shared by both commands)

`GET /repos/{o}/{r}/labels?per_page=100&page=N` for N = 1.., with `retries=3`. The listing stops at the first page with fewer than 100 items.
- A `None` result on page 1 (404, or no access) → `repo_not_found`. A `None` result on any later page → `label_list_failed`. A past-the-end page returns `[]`, not `None`, so `None` there is an anomaly and is never read as "end of list" (architect R1).
- Every list and confirm call is a plain GET with no `--input`. The create call passes `--method POST` explicitly. Never rely on `gh api` inferring the method from `--input` (architect R1).
- `GitHubError`/`RateLimitError` → `label_list_failed`.
- A non-list body → `label_list_failed`.
- Reaching page `LABEL_PAGE_BOUND` while it still holds 100 items → `label_list_truncated`. The run fails closed: it never claims "missing" over a partial list.

The result is a mapping `casefold(name) → {name, color, description}`.

### 6.4 `check` algorithm

- `expected` = `provisionable(reg)`.
- For each expected spec `s`, look up `repo[casefold(s.name)]`:
  - absent → `missing`.
  - present → compare. Collect the reasons, in this order: `name-case` (exact name differs), `color` (`actual.color.lower() != s.color`), `description` (`(actual.description or "") != s.description`). If there are any reasons, the label goes in `present_unprovisioned` as `{name, reasons, actual: {name, color, description}}`. Otherwise it is `present`.
- `present_not_provisionable` = registry labels **not** in `expected` (`provision: false` or `retired`) that exist in the repo. This is informational. Example: a hand-applied `hos-halt`.
- Repo labels not in the registry are counted (`unregistered_count`) and never listed or judged.
- **Exit:** 0 if `missing` is empty; 1 if it is not; 2 on any error. `present_unprovisioned` never changes the exit code, because it is present (ADR AD-7: "0 when everything is present"). This is the VF-12 detector, and it is reported, not failed.

### 6.5 `provision` algorithm

1. Run §6.3 and compute `to_create` = §6.4's `missing`, sorted by name. Only provisionable specs can be in it.
2. **Dry run (default):** perform no POST. Exit 0. `to_create` is the plan.
3. **`--apply`:** for each `s` in `to_create`, in order, call `POST /repos/{o}/{r}/labels` with `stdin_json={"name": s.name, "color": s.color, "description": s.description}` (exactly these three keys) and `retries=0`. A create is not idempotent at the transport level, and a timed-out POST may have landed (`github.py:57-63`).
   - Success → `created`.
   - `GitHubError` with `status_code == 422` (already exists: a race or a case variant) → confirm with `GET /repos/{o}/{r}/labels/{urllib.parse.quote(s.name, safe="")}` (`retries=3`). If it is present, the label goes in `existed_concurrently`. If not, `failed`.
   - Any other `GitHubError`/`RateLimitError` → `failed` (`{name, status_code, message}`) and **continue** with the rest.
4. After the loop, re-run §6.3 (the post-apply verify). Compute `missing_after` with §6.4.
5. **Exit:** 2 if step 1 or step 4 errored. 1 if `failed` or `missing_after` is non-empty. Otherwise 0.
6. **Never** `PATCH`, `DELETE` or `PUT`, on any path. The only write is `POST /repos/{o}/{r}/labels`.

**Idempotence:** on a second `--apply` against the same repo, `to_create` is empty, so there are zero POSTs (LP-4).

**Request budget:** check is `ceil(L/100)` GETs (1 for this repo). Apply is at most 2 × 10 GETs plus `|to_create|` POSTs plus one confirm GET per 422.

### 6.6 Output contract

- **stdout:** exactly one JSON object on every path that reaches `main`, including usage errors. It is written with `json.dumps(obj, sort_keys=True, indent=2)` and a trailing newline.
- **stderr:** exactly one summary line, prefixed `labels_cli: `. On error it is `labels_cli: <code>: <message>`. The token value never appears in either stream.

Fields:

```
common:    schema ("hos.labels-cli/1"), command ("check"|"provision"|null on usage), app, repo,
           registry_digest (null if not loaded), exit_code, error (null | {code, message, path}),
           audit_record (relpath | null)
check:     expected[], present[], missing[], present_unprovisioned[], present_not_provisionable[],
           unregistered_count, requests
provision: mode ("dry-run"|"apply"), to_create[], created[], existed_concurrently[], failed[],
           missing_after[] (apply only; [] in dry-run), present_unprovisioned[], requests
```

### 6.7 Audit record (one per run that parsed its arguments)

- `event`: `labels-checked` (check) or `labels-provisioned` (provision, both modes).
- Fields: `timestamp` (`_now_iso()`), `schema_version: 1`, `app`, `bot_login` (`env.get("HOS_BOT_LOGIN")` or null), and every stdout field except `audit_record`.
- Written to `<repo_root>/audit/log/` through `audit_log.write_event`.
- A usage error writes nothing, because there is no command to record.
- **Fail closed:** if the write raises, the run exits 2 (`audit_write_failed`), whatever the outcome would have been. Any labels already created stay created. They are idempotent, and a re-run records them as present.

---

## 7. L3: `bootstrap/provision_labels.sh`

### 7.1 Shape (a copy of `bootstrap/pr_review.sh:131-252`, reduced)

```
bash bootstrap/provision_labels.sh check     --app <worker|overseer|human> [--repo <o/r>]
bash bootstrap/provision_labels.sh provision --app <worker|overseer|human> [--repo <o/r>] [--apply]
```

The script does the following, in order:
1. `set -euo pipefail`. Resolve `SCRIPT_DIR` and `REPO_ROOT`.
2. **Extract, do not validate** (merge_authority.sh's ARCH-3a idiom). `SUBCOMMAND` is `$1` if it does not start with `-`. `APP_ROLE` comes from `--app X` or `--app=X`. Mint only if `SUBCOMMAND ∈ {check, provision}` **and** `APP_ROLE ∈ {worker, overseer, human}`. That is the wrapper's only `case`.
3. Install revoke traps, copied from `pr_review.sh`:
   - an idempotent `revoke_token` that deletes the token file and calls `bash "$SCRIPT_DIR/revoke_app_token.sh"`;
   - `trap revoke_token EXIT`;
   - INT/TERM handlers that revoke and then re-raise the signal.
3a. **Scrub the inherited credentials, unconditionally and before the mint decision is acted on (architect R1, binding; §18.2).** Run `unset GH_TOKEN GITHUB_TOKEN HOS_BOT_LOGIN HOS_EXPECTED_BOT_LOGIN HOS_LABELS_TOKEN_MINT_FAILED`. This step is **not** in `pr_review.sh`, and leaving it out is a defect there. Without it, two things go wrong:
   - **The caller's token gets revoked.** `revoke_app_token.sh` revokes whatever `GH_TOKEN` it inherits. On a no-mint or failed-mint path, that is the caller's own token. S3a will call this wrapper from inside `bin/hos-cron`'s cycle, so the cycle's working token would be revoked mid-cycle by a read-only preflight.
   - **Ambient auth gets used, and the audit lies.** Any argv that L3 reads differently from L2 (no mint, but L2 still parses) would run L2 under an inherited token, and the audit's `bot_login` would be the caller's, not this run's.

   After this step, the mint is the **only** source of `GH_TOKEN` and `HOS_BOT_LOGIN`, which is what §7.3 claims. It is environment hygiene for the token this wrapper owns, so it falls under the minting carve-out in §18.2, not AD-1a's "mutate its environment" clause.
4. Mint: `TOKEN_FILE="$(mktemp)"`, then `bash "$SCRIPT_DIR/get_app_token.sh" --app "$APP_ROLE" > "$TOKEN_FILE"`.
   - On success, source the file.
   - On failure, `export HOS_LABELS_TOKEN_MINT_FAILED=1` and write one stderr warning line.
   - Either way, `rm -f` the file at once. A stale inherited `HOS_LABELS_TOKEN_MINT_FAILED` has already been cleared by step 3a.
5. Interpreter ladder (copied from `invoke_agent.sh`, without its override variable):
   - use `"$REPO_ROOT/scripts/oversight/.venv/bin/python"` if it is executable;
   - otherwise `python3` if it is on PATH;
   - otherwise one stderr line naming `bash scripts/oversight/ensure_venv.sh` and `exit 1`.
6. Run `"$PYTHON" "$REPO_ROOT/scripts/framework/labels_cli.py" "$@"` under `set +e` and capture `RC`. **Not `exec`**, so the EXIT trap revokes after the run. Then `exit "$RC"`.

**The wrapper must never:** write to stdout; contain `jq` or a JSON literal; validate, default or reorder any argument; add a flag; or read `--repo`/`--apply`. Every exit code except the ladder's `1` is L2's. LW-7 enforces this statically.

Header text: a usage block, an exit-code table (copied from §6.4/§6.5), "stdout is labels_cli.py's, byte-for-byte", "never suppress this script's stderr (#1523)", and the identity note in §7.3.

### 7.2 Exit codes (pass-through)

| Code | check | provision |
|---|---|---|
| 0 | every provisionable label is present | dry run computed, or apply with no failures and nothing missing after |
| 1 | at least one provisionable label is missing (or the wrapper's own no-interpreter line) | apply had a failed create or `missing_after` is non-empty |
| 2 | error: usage, token, repo, registry, list, truncation or audit | same |

### 7.3 Identity

- Label creation emits no issue or PR events, so the token's identity cannot mint authorization (ADR AD-7, AD-5). Any HOS App role is acceptable.
- What the wrapper does guarantee: it **never** runs under ambient or personal `gh` auth. L2 refuses when there is no `GH_TOKEN` (§6.2), and the only `GH_TOKEN` source in the wrapper is the App mint.
- The AD-5 bot-identity guard (`HOS_BOT_LOGIN == HOS_EXPECTED_BOT_LOGIN` and `is_bot_reviewer`) belongs to `migrate` (S6a). It is deliberately not added here.

### 7.4 H-1's exact commands (for `docs/LABELS.md` and the H-1 comment)

```
bash bootstrap/provision_labels.sh provision --app human            # dry run: review to_create
bash bootstrap/provision_labels.sh provision --app human --apply
bash bootstrap/provision_labels.sh check --app human                # post this stdout on #1520
```

The ADR's H-1 shorthand (`provision_labels.sh --apply`) maps to the second line. The subcommand and `--app` are mandatory, because the wrapper has a fixed argv.

---

## 8. Conformance: `tests/framework/test_label_conformance.py` + `scripts/framework/label_literal_allowlist.txt`

### 8.1 Shared definitions

- **Live-code scope (P1, P5):** the `git ls-files -c -- bin bootstrap scripts .github/workflows` output, excluding paths ending `.md`. This is VF-1's "Live code" class. Agent definitions and prompts are excluded (§13).
  - Read each file from the working tree as UTF-8. Skip files that fail to decode or no longer exist.
  - Use tracked files only, so a stray untracked scratch file cannot fail a local run. CI sees every committed file.
- **Whole-repo scope (P4):** `git ls-files -c` with the same reading rules.
- **The registry** is `label_registry.load(ROOT)`. The name set is `set(reg.labels)`, which includes family-expanded names.

### 8.2 Allowlist file format

```
# <header comment: protected surface; never widen without the CODEOWNERS gate; how sections work>
[historical]
<glob>            # require_human_approval.glob_to_regex semantics
...
[legacy-readers]
<exact path>
...
[pending]
<exact path>
...
```

The parser lives in the test as `_load_allowlist(path) -> dict[str, list[str]]`. These are **failures** in their own right (C-1):
- an entry before the first header;
- an unknown, missing, repeated or out-of-order section (the order is fixed as above);
- a duplicate entry anywhere;
- `*`, `?` or `[` in a `[legacy-readers]`/`[pending]` entry;
- a path listed in both `[legacy-readers]` and `[pending]`;
- a `[legacy-readers]`/`[pending]` path that a `[historical]` glob matches (redundant).

Blank lines and `#` lines are ignored, and entries are stripped.

### 8.3 P1: label-bearing shapes (patterns are data: a module-level `SHAPES` tuple)

Let `N = [a-z0-9][a-z0-9:._-]*`, `LIST = N(?:,N)*`, `END = (?![A-Za-z0-9:._{$<-])`, and `QN = \\?["'](N)\\?["']` (a quoted name, tolerating `\"` escapes). Each shape has an id, a regex applied **per line**, an extraction rule and a role (used by P5):

| id | regex (Python, per line) | names extracted | role |
|---|---|---|---|
| `flag` | `--(add-label\|remove-label\|label)(?:=\|\s+)(["']?)(LIST)END` | group 3 split on `,`. **If group 2 is empty (unquoted), keep only names containing `-` or `:`.** This drops prose such as `--label accepts …`. | `write` for add/remove, `either` for `--label` |
| `query` | `[?&]labels=(LIST)(?=[&"'\s)\\]\|$)` | group 1 split on `,` | `read` |
| `labels_to_add` | `labels_to_add\s*=\s*\[([^\]]*)\]` | `QN` over group 1 | `write` |
| `labels_json` | `(?:\\?["']labels\\?["']\s*:\|\blabels=)\s*\[([^\]]*)\]` | `QN` over group 1 | `write` |
| `label_str` | `\blabel\s*:\s*str\s*=\s*["'](N)["']` | group 1 | `write` |
| `excluded` | `^\s*EXCLUDED_LABELS\s*=(.*)$` | `QN` over group 1 | `read` |
| `human_gate` | `^\s*_HUMAN_GATE_LABELS\s*=(.*)$` | `QN` over group 1 | `read` |
| `known` | `^\s*KNOWN_LABELS="([^"]*)"` | group 1 split on `\|` | `catalog` |
| `bash_glob` | `\*"\s(N)\s"\*` | group 1 | `read` |
| `label_default` | `["']--label["'].*\bdefault=["'](N)["']` | group 1 | `read` |

A hit is `(name, shape_id, role, path, lineno)`.

**P1 assertion:** every hit's `name` is in the registry, or `family_for(reg, name)` is not `None`. The failure message lists every offending `path:line name shape`.

**Measured result** (a prototype of exactly these patterns over the live-code scope at `c48c8ddd0`). The distinct names hit are: `design-concern`, `hos-autowork-authorized`, `hos-budget-gated`, `hos-claimed`, `hos-coordination`, `hos-embargo`, `hos-halt`, `needs-ai`, `needs-coordination`, `needs-human`, `priority:critical`, `priority:high`, `release-authorized`, `release-request`, `wontfix`. There are no false positives. `needs-coordination` is the only non-registry name, and §9 removes it. Every other name is a §3.2 entry. **The coder must reproduce this set**. If the implemented patterns hit any other name, stop and return to `technical-design`. Do not widen the registry.

### 8.4 P2–P6

- **P2 (doc bijection).** In `docs/LABELS.md`, locate the line that equals `| Label | Writers | Control-flow effect | Notes |`. The table is the contiguous run of following lines that start with `|`, skipping the `|---|…` separator. For each row, the first cell is the text between the first and second `|`. Its names are every backtick span in that cell. Assert:
  - no name appears in two rows;
  - the set of names equals `set(reg.labels)`;
  - exactly one header line exists, and no line after the table's end and before EOF starts with `` | ` `` (this catches a table split again, as it is today).
- **P3 (declared paths are real).** For every label and every path in `writers ∪ readers`, the path is a file under ROOT and its text contains the label's name as a substring.
- **P4 (ratchet).** `H` = whole-repo files whose text contains `needs-ai`. Assert:
  1. every file in `H` is matched by a `[historical]` glob, or is in `[legacy-readers]` or `[pending]`;
  2. every `[pending]` path is in `H`. A stale entry fails with the message "remove it from [pending]: it no longer contains needs-ai";
  3. every `[legacy-readers]` path exists.

  The literal `needs-ai` is the test's only hard-coded label literal, and the test file is therefore in `[legacy-readers]`.
- **P5 (status consistency)**, over the P1 hits:
  - `planned`: no hit with a role other than `catalog`.
  - `legacy-read`: no hit with role `write` or `either` in a file outside `[pending]`.
  - `retired`: no hit with a role other than `catalog` in a file outside `[legacy-readers]`.
  - `active`: no constraint.

  At S1 this means: `needs-worker`, `needs-overseer`, `hos-autowork-authorized`, `hos-in-progress` and `suppression-expired` have only `catalog` hits or none, and nothing is `legacy-read` or `retired`.
- **P6 (patterns cannot rot).** A `FIXTURES` table in the test holds, for **each** shape id, at least one positive fixture line with its exact expected `(name…)` extraction, plus these negatives, which must yield nothing:
  - `--label accepts a comma-separated list`
  - `--label is not supported with edge modes`
  - `labels={encoded_label}`
  - `labels=${LABEL_FILTER}`
  - `--label "$LABELS"`
  - `--add-label <a,b>`
  - `labels = [lbl.get("name", "") for lbl in x]`
  - `f"priority:{name}"`

  Assert that every shape id has at least one positive fixture, and that every fixture's extraction equals the expected one exactly.

### 8.5 Initial allowlist content (S1)

`[historical]` (ADR AD-8, verbatim):

```
docs/v*/ADR-*
docs/v*/REQUIREMENTS-*
docs/v*/TECHNICAL-DESIGN-*
docs/v*/PANEL-*
docs/v*/SPEC-*
docs/specs/**
docs/releases/**
research/**
prompts/**
audit/**
DECISIONS.md
docs/issue-reference-*.md
docs/planning/**
```

`[legacy-readers]`:

```
contract/labels/core.yaml
docs/LABELS.md
scripts/framework/label_literal_allowlist.txt
tests/framework/test_label_conformance.py
tests/framework/test_labels_cli.py
```

`[pending]`: the 37 files below. They are the 38 non-historical `needs-ai` files measured in §1, minus `docs/LABELS.md`:

```
.claude/agents/overseer.md
.claude/agents/pm-agent.md
.claude/agents/worker.md
.claude/commands/hos-triage.md
.github/workflows/label-swap.yml
CLAUDE.md
METHODOLOGY.md
bin/hos-cron
bootstrap/create_issue.sh
bootstrap/escalate_to_human.sh
bootstrap/overseer-cron-prompt.md
bootstrap/worker-cron-prompt.md
contract/OVERSIGHT-CONTRACT.md
docs/AGENTS.md
docs/COST-MANAGEMENT.md
docs/CRON-SETUP.md
docs/CROSS-REPO-CONDUCT.md
docs/OVERSIGHT-RUNBOOK.md
scripts/automation/lib/merge_authority.py
scripts/automation/lib/probe.py
scripts/automation/lib/self_review_source.py
scripts/framework/check_agents_static.sh
scripts/framework/select_work_candidates.py
tests/automation/test_create_issue.py
tests/automation/test_edit_issue.py
tests/automation/test_escalate_to_human.py
tests/automation/test_hos_cron.py
tests/automation/test_phase_b.py
tests/automation/test_probe.py
tests/automation/test_query_issues.py
tests/automation/test_query_issues_edges.py
tests/framework/test_requester_trust.py
tests/framework/test_select_work_candidates.py
tests/framework/test_select_work_candidates_ghshim.py
tests/framework/test_select_work_candidates_native.py
tests/framework/test_selection_call_sites.py
tests/oversight/test_agents_static_logic.py
```

**Files that must not contain `needs-ai` (architect R1).** These new or edited files are in neither `[legacy-readers]` nor `[pending]`, so P4 fails if any of them contains the literal, including in a comment, docstring or usage block:
- `bootstrap/provision_labels.sh`;
- `scripts/automation/lib/label_registry.py` and `scripts/framework/labels_cli.py` (C-10 already covers these two);
- `tests/automation/test_dimension_registry.py`;
- `SCRIPTS-INDEX.md`. This one is generated from the new scripts' header lines, so keep those lines free of label names.

If `test_labels_cli.py`'s fixtures do not contain `needs-ai`, it may stay in `[legacy-readers]`, because P4 rule 3 only requires existence. This design does **not** require the CLI tests to use `needs-ai`: their fixture registry may use any names.

---

## 9. `KNOWN_LABELS` fix

`scripts/framework/check_agents_static.sh:170` becomes:

```
KNOWN_LABELS="needs-human|needs-ai|needs-worker|needs-overseer|hos-coordination|hos-claimed|hos-halt|hos-budget-gated|hos-embargo|hos-autowork-authorized|release-request|release-authorized"
```

This replaces `needs-coordination` with `hos-coordination` and adds `needs-worker|needs-overseer` before S4 (ADR AD-8). Change nothing else in the script. After the edit, `bash scripts/framework/check_agents_static.sh` must still exit 0 (C-9 runs it).

`tests/oversight/test_agents_static_logic.py`:
- `_LABELS` becomes the same string.
- Add `test_classify_pending_actor_labels`: `needs-worker` and `needs-overseer` classify `SKIP`.
- Add `test_classify_coordination_label_spelling`: `hos-coordination` classifies `SKIP`, and `needs-coordination` classifies `CHECK` (it has a hyphen and is no longer a label).
- That module is binding-6 pure (no file I/O), so the shell-to-registry tie lives in the conformance test (C-8), not here.

---

## 10. `docs/LABELS.md` edits (prose half of the one registry)

1. **Repair the table.** Move the whole "The `needs-ai` authorizing act (the durable reference home …)" section, unchanged, to directly after the table. Keep the heading text byte-identical, because `label-swap.yml:88` cites it by name. The table becomes one contiguous block.
2. **Add rows**, in the existing four-column format:
   - `needs-worker`, `needs-overseer`: "Planned (#1520). Registered and provisionable. No code writes or reads it yet. See ADR-1520 AD-3 for semantics."
   - `wontfix`: writer `label-swap.yml` `/decline`; reader `triage.py:270` (closes as not actionable).
   - `design-concern`: writer `scripts/review_self.sh:326`; reader `issue_query.py` risk-label list.
3. **Fix citations:** `merge_authority.py:633` → `:634`, `:1223` → `:1268` (VF-11), and `check_agents_static.sh:158` → `:170`. In the `hos-coordination` row's Notes, replace the "pre-existing mismatch … tracked as a follow-up" sentence with "Fixed in #1520 S1."
4. **"Pending rename" paragraph:** add one sentence saying that `needs-worker`/`needs-overseer` are now registry entries with status `planned` in `contract/labels/core.yaml`, and are still not live.
5. **Add a section "Registry data and tooling"** after the authorizing-act section. It covers:
   - `contract/labels/core.yaml` is the data half and this table is the prose half. The conformance test enforces the bijection (P2).
   - The status vocabulary.
   - `provision: false`.
   - The `families:` extension point (for #1644 T3.1).
   - The §7.4 commands.
   - The meaning of `present-unprovisioned` (reported, never modified).
   - The allowlist ratchet (one sentence each on `[historical]`, `[legacy-readers]` and `[pending]`).
   - **No table in this section, or anywhere after the label table, may have a row that starts with `` | ` `` (architect R1).** P2's split-table guard would fail on it. Write the status vocabulary as a bullet list.
6. **"Known gaps":**
   - Delete the "No idempotent provisioning path" and "No conformance test" bullets. Replace them with one bullet: "Consumer installs do not yet receive the registry or the tool (ADR-1520 S6b, ARCH-ESC-1)."
   - Keep the rename bullet, but update "~65 files" to point at `label_literal_allowlist.txt` `[pending]` as the live count.
   - Rewrite the `KNOWN_LABELS` bullet: it is still a separate, narrower list, but P1 now requires every name in it to be a registry entry.

---

## 11. `SCRIPTS-INDEX.md`

Regenerate with `bash scripts/framework/gen_scripts_index.sh` after the new scripts exist. `tests/framework/test_scripts_index.py` must pass.

---

## 12. Test plan (named cases; all must pass)

All CLI tests run in-process through `labels_cli.main(argv, repo_root=tmp_root, env={...})`, with `monkeypatch.setattr(labels_cli, "_gh", fake)` and a stateful `FakeRepo(labels)` that records `(method, endpoint, body)`. `tmp_root` holds a copy of `contract/labels/core.yaml` (or a fixture registry) and `contract/resolved-packs.txt` (empty). `_origin_url` is monkeypatched. Wrapper tests run the real bash script in a fixture tree with stubbed `get_app_token.sh`, `revoke_app_token.sh` and a `labels_cli.py` stub, using `pr_review_wrapper`'s harness idiom and `tests.tmp_hygiene.child_env`. Nothing touches the network.

**Loader (`test_labels_cli.py`, LR-\*)**

| id | Asserts |
|---|---|
| LR-1 | The shipped `contract/labels/core.yaml` loads. It has exactly the 20 §3.2 names, and `families == ()`. |
| LR-2 | Table-driven: each rule LR-0..LR-13 yields its code. Cases include a `000000` YAML int color (`bad_color`), `Needs-AI` vs `needs-ai` (`duplicate_id`), a 101-char description, and a writer `../x` (`path_escape`). |
| LR-3 | CORE-only: a `pack-x.yaml` with only a header (with `packs=["x"]`) → `core_only`; a `project.yaml` with `labels:` → `core_only_key` (engine). |
| LR-4 | Families: a fixture provider registered via `monkeypatch.setitem(sys.modules, "scripts.automation.lib._label_fixture_provider", mod)` contributes `stage:plan`. `stage:plan` then appears in `reg.labels` with `family="stage:"`. A provider name outside the prefix → `family_provider_failed`; a provider that raises `KeyError` → `family_provider_failed`; a provider path `os:system` → `bad_family`; a static name `stage:x` → `family_collision`; duplicate prefixes `stage:`/`stage:` → `bad_family` (second-review R1). |
| LR-5 | `to_json` is deterministic. The digest changes when any field changes and is stable across key order in the YAML. |
| LR-6 | `provisionable()` excludes `provision: false` and `retired`, and includes `planned` and `legacy-read`. |
| LR-7 | `dimension_registry.registered_schemas() == ("hos.dimension-registry", "hos.label-registry")`. |
| LR-8 | Installed tree: `.hos-release` present and `contract/labels/core.yaml` without a `.hos-manifest` row → `installed_drift`, with `path == "contract/labels/core.yaml"` (the engine's L31 applies to the new kind unchanged). The fixture **must** give `contract/resolved-packs.txt` a valid WHOLE row. L31 checks that file first, so without the row the test would pass on the wrong path (architect R1). |

**CLI (`test_labels_cli.py`, LC-\*/LP-\*)**

| id | Asserts |
|---|---|
| LC-1 | `check`: all provisionable present → exit 0, `missing == []`, one GET. |
| LC-2 | `check`: `needs-worker` absent → exit 1, `missing == ["needs-worker"]`. |
| LC-3 | `check`: wrong color → exit 0, `present_unprovisioned[0].reasons == ["color"]`. `NEEDS-HUMAN` in the repo → reasons include `name-case`. |
| LC-4 | `check`: `hos-halt` present in the repo → listed in `present_not_provisionable`, exit unaffected. |
| LC-5 | List `GitHubError` → exit 2 `label_list_failed`. Page-1 `None` → `repo_not_found`. 10 full pages → `label_list_truncated`. |
| LC-6 | Corrupt registry → exit 2, `error.code == "registry:bad_color"` (for example), zero GitHub calls. |
| LC-7 | No `GH_TOKEN` → `no_token`. `HOS_LABELS_TOKEN_MINT_FAILED=1` → `token_mint_failed`. Both make zero GitHub calls. |
| LC-8 | Usage: no subcommand, `migrate`, `--apply` on `check`, `--app robot`, `--repo a/b/c`, `--repo ../..` → exit 2 `usage`, zero calls, no audit record. Also (architect R1): `--app worker check` (flag before subcommand), `check --ap worker` (abbreviation), `check --app worker --app=human` (repeated) → `usage`. |
| LC-9 | `--repo` default parsed from `git@github.com:o/r.git` and `https://github.com/o/r`. Unparseable → `repo_unresolved`. |
| LC-10 | Parametrized over every path above: stdout parses as exactly one JSON object, with `exit_code` equal to the return value. |
| LP-1 | `provision` dry run with 3 missing → exit 0, `to_create` sorted, **zero POSTs**. |
| LP-2 | `--apply`: missing `hos-halt` (provision false), a `retired` fixture label and `hos-in-progress` are **never** POSTed. Missing `needs-worker`/`needs-overseer` are POSTed. |
| LP-3 | `--apply` with `present_unprovisioned` entries: the recorder shows only `GET …/labels*` and `POST /repos/o/r/labels`. There is **no** PATCH, DELETE or PUT. |
| LP-4 | Idempotence: two `--apply` runs on one `FakeRepo` → the second makes **zero POSTs** and exits 0. |
| LP-5 | 422 on a POST, then the confirm GET finds it → `existed_concurrently`, exit 0. Confirm GET 404 → `failed`, exit 1. |
| LP-6 | One POST raises a 500 → the others are still attempted, the 500 one is in `failed`, exit 1, `retries == 0` was passed for every POST. |
| LP-7 | POST body keys are exactly `{name, color, description}`, with the registry's values. |
| LP-8 | Audit: one `labels-checked`/`labels-provisioned` record under `tmp_root/audit/log/`, with `registry_digest`, `app`, `bot_login`, `exit_code`, and no `GH_TOKEN` value anywhere in its bytes. An `_audit_write` that raises → exit 2 `audit_write_failed`. |
| LP-9 | A fixture family's labels are provisioned like static ones. |

**Wrapper (`test_labels_cli.py`, LW-\*)**

| id | Asserts |
|---|---|
| LW-1 | `check --app worker` and `provision --app=human` → the stub `get_app_token.sh` is called once with `--app <role>`. |
| LW-2 | `bogus --app worker`, `check` with no `--app`, and `check --app robot` → no mint. L2's exit 2 passes through. |
| LW-3 | Revoke is called exactly once on a normal exit, and once on SIGTERM to the wrapper (the parent sees 143). |
| LW-4 | Exit codes 0, 1 and 2 from the stub L2 pass through unchanged. The wrapper writes nothing to stdout itself (its stdout equals the stub's). |
| LW-5 | A failing mint → the stub L2 sees `HOS_LABELS_TOKEN_MINT_FAILED=1`. An inherited `=1` with a successful mint is cleared. |
| LW-6 | Ladder: a fixture `scripts/oversight/.venv/bin/python` (symlink to `sys.executable`) is preferred over `python3`. |
| LW-7 | Static: the wrapper source contains no `jq`, no `exec "$PYTHON"`, no `echo`/`printf` to stdout, and the only `case` is the mint decision. `labels_cli.py` is referenced exactly once. |
| LW-8 | (architect R1) The caller exports `GH_TOKEN=sentinel-inherited` and `HOS_BOT_LOGIN=someone`. On each of the no-mint path (`bogus --app worker`) and the failed-mint path, the stub L2 sees **no** `GH_TOKEN` and **no** `HOS_BOT_LOGIN`. The stub `revoke_app_token.sh` records the `GH_TOKEN` it was given, and that record is never `sentinel-inherited`. On the successful-mint path, both the stub L2 and the stub revoke see only the stub-minted value. |
| LW-9 | (architect R1) Static: the `unset` of §7.1 step 3a appears before the first `get_app_token.sh` reference, and it names all five variables. |

**Conformance (`test_label_conformance.py`)**

| id | Asserts |
|---|---|
| C-1 | The allowlist parses, under every rule in §8.2 (with negative fixtures for each parser rule). |
| C-2 | P1 (§8.3). |
| C-3 | P2 (§8.4). |
| C-4 | P3. |
| C-5 | P4 rules 1–3. |
| C-6 | P5. |
| C-7 | P6. |
| C-8 | The `KNOWN_LABELS` value (extracted by the `known` shape from `check_agents_static.sh`) ⊆ registry names, ⊇ `{needs-worker, needs-overseer, hos-coordination}`, and excludes `needs-coordination`. |
| C-9 | `bash scripts/framework/check_agents_static.sh` exits 0, with a subprocess timeout of 120 s. |
| C-10 | `label_registry.py` and `labels_cli.py` contain none of the registry's names as substrings (one source of truth). |
| C-11 | There is no `packs/*/labels.yaml` (CORE-only, ADR AD-7). |

**Non-regression (must pass unchanged, except T5.43's one line):** `tests/automation/test_dimension_registry.py`, `tests/automation/test_dimension_registry_data.py`, `tests/framework/test_install_registry_data.py` (static T5.44 and the slow install tests), `tests/framework/test_consumer_framework_files.py`, `tests/framework/test_scripts_index.py`, `tests/oversight/test_agents_static_logic.py`. Also run `bash scripts/framework/run_tests_inner_loop.sh`, and run `scripts/oversight/run_gates.sh` on the changed files.

---

## 13. Boundaries and non-goals

- **No behavior change.**
  - No existing reader or writer changes, `select_work_candidates.py`'s `--label` default stays `needs-ai`, and nothing calls `labels_cli.py` (the `bin/hos-cron` preflight is S3a).
  - No `migrate` subcommand (S6a).
  - No `pending_actor_labels.py` (S2a).
- **No consumer shipping.** S1 does not add `contract/labels/core.yaml`, `label_registry.py`, `labels_cli.py` or `provision_labels.sh` to `framework_consumer_files.txt`, and does not add a `.gitattributes` line. `scripts/automation/lib/**` is not shipped to consumers today at all (`framework_consumer_files.txt:16`, withheld until #1643 W7). That is S6b's job, under ARCH-ESC-1 (TD-ESC-2).
- **No new public `github.py` helpers.** `labels_cli._gh` is the single seam over `_run_gh`, which follows `probe.py`'s precedent. A later slice that needs label reads elsewhere (S6a) should promote `list_labels`/`create_label` into `github.py` then.
- **P1 scope is live code only.** Agent definitions and prompts use further labels (`spec-gap`, `security-finding`, `privacy-finding`, `resolved-in-review`, `bug`; prototype scan of `.claude/agents/**`). They are outside VF-1's "live code" class and are **not** registered in S1. This is a candidate follow-up, not part of this slice.
- **The loader never touches the network or the environment.** The CLI never reads `config.sh`.

---

## 14. Risk tier and required reviewers

- **Tier: MEDIUM.** The ADR (§3) classes S1 as MEDIUM-class tooling. Every touched path is protected, so the CODEOWNERS human gate applies whatever the tier.
- **Reviewers:**
  - `code-reviewer`;
  - `security-reviewer` (a new token-minting wrapper; a GitHub write path; a YAML-named import in LR-10/LR-12);
  - `reliability-reviewer` (GitHub dependency: bounded pagination, `retries=0` on POST, the 422 race, fail-closed truncation);
  - `ops-reviewer` (two new audit event names; S5 documents them in OVERSIGHT-CONTRACT.md);
  - cross-vendor second review at the assessed tier.

  `unit-test` covers §12.
- The risk-assessor's validators decide the final tier. If `tier_floor` comes out above MEDIUM, that governs.

---

## 15. Startup-gap and affected sign-offs

*Should this have been settled before code was written against it?* Two small items are ADR-level facts that design-time grounding corrected. Neither has any code written or approved against it.

1. **The ADR's S1 file list omits `tests/automation/test_dimension_registry.py`.** T5.43 pins `registered_schemas()` to one schema, so S1 must edit it (one line). This is clarifying, and it stays within the 15-file cap.
2. **The ADR says the `_REGISTRY_KINDS` row ships `contract/labels/`** (AD-7 "the installer ships it"; AD-10 step 1). In fact the row only handles `pack-*.yaml` files. `core.yaml` ships through `framework_consumer_files.txt`, and the loader modules are not shipped at all yet. S1 is unaffected. S6b's TD must add the shipping rows (TD-ESC-2).

**Affected sign-offs:**
- ADR-1520's architect acceptance stands. Neither item changes a decision.
- TD-1644-T3.0b, TD-1604 and TD-1540 S2 are unaffected by S1 (ADR §5's analysis stands).
- No register entry exists for S1. No approval is orphaned.

No `startup-artifact-gap` issue is opened. The ADR is days old and unbuilt, so these are routine design corrections, recorded here and routed to the architect (§16). This TD does not file issues (the task forbids GitHub writes). If the architect judges item 2 a gap, the worker annotates #1520.

---

## 16. Escalations (TD-ESC)

**TD-ESC-1 (to `architect`; non-blocking: default stated). RULED in §18.2: the default is adopted, with one added binding condition.**
- ADR-1520 AD-7 calls for `provision_labels.sh` "per ADR-1643 AD-1/AD-1a". But AD-1a's text forbids an L3 to "read or branch on any element of `$@`" or "mint or revoke a token".
- ADR-1643 §10.4 scopes AD-1a to `invoke_agent.sh`, and explicitly leaves `merge_authority.sh`'s token-minting L3 unamended. ADR-1520 AD-5 also says the S6a tool mints "using the `edit_issue.sh` pattern", which mints in bash.
- **Default this design takes:**
  - adopt AD-1a's interpreter ladder and its no-stdout, no-JSON, pass-through rules;
  - follow `pr_review.sh`'s precedent for minting: extract `--app` without validating it, mint, revoke on exit and on signal.
- **Alternative if the architect rules otherwise:** L2 invokes `get_app_token.sh` itself as a subprocess and parses its export lines. I advise against this. It re-implements the sourced-file contract in Python, and it puts token handling in a module that otherwise has no secrets.

**TD-ESC-2 (to `architect`; non-blocking for S1; blocks the S6b TD). RULED in §18.3: S6b ships what it needs itself, and does not wait for #1643 W7.**
- The ADR's consumer path (AD-10 step 1) assumes the `_REGISTRY_KINDS` row ships the registry. It does not (§15 item 2).
- S6b must also ship `scripts/automation/lib/{dimension_registry,label_registry,posture}.py`, `scripts/framework/labels_cli.py`, `bootstrap/provision_labels.sh` and `contract/labels/core.yaml` (with a `.hos-manifest` WHOLE row and a `contract/labels/** -text` `.gitattributes` line, so the engine's L31 holds).
- Today `framework_consumer_files.txt:16` withholds the registry modules until #1643 W7. **Question:** does S6b depend on #1643 W7, or does S6b ship the modules itself? This is an architecture sequencing call, and it does not concern S1's code.

No product (`pm-agent`) or human escalation is raised. S1 needs no human ruling to be coded (ADR S1 row), and this design keeps that true.

---

## 17. Architect review request (round 1 of 5)

Please review, in particular:
- §4.3's rule order and the LR-10 provider restriction;
- §6.4's decision that `present-unprovisioned` does not change `check`'s exit code;
- §8.3's measured pattern set and the unquoted-name heuristic;
- §3.2's `planned` + `provision: false` treatment of the three spec-stage names;
- TD-ESC-1 and TD-ESC-2.

On approval, change Status to APPROVED and hand the design to `coder`.

---

## 18. Architect review (round 1 of 5): APPROVED_WITH_CHANGES

Reviewer: `architect`, 2026-10-20. Reviewed against ADR-1520 (merged `c48c8ddd0`) and ADR-1643 §10.1/§10.4/§10.5, at `a6459b847`. The changes are inline, marked "(architect R1)". No round 2 is needed: every change is a stated fix, not an open question.

### 18.1 Fidelity to ADR slice S1

**Verdict: faithful.** I re-measured the TD's claims rather than accepting them.

**The measured claims all reproduce.**
- **P1.** A prototype of exactly §8.3's ten shapes, over the §8.1 live-code scope at `a6459b847`, gives exactly the 15 names §8.3 lists. `needs-coordination` is the only non-registry name.
- **P3.** Every `writers`/`readers` path in §3.2 exists and contains its label.
- **P4.** `git grep -l needs-ai` returns 126 files, because this TD adds one historical file. Of those, 38 fall outside `[historical]`. They are exactly §1's list.
- **C-9.** `check_agents_static.sh` exits 0 today, in about 7 s.
- **No runtime iteration of `KINDS`.** No code in `scripts/`, `bin/` or `bootstrap/` iterates `KINDS` or calls `registered_schemas()`. The new row is inert to every existing path.

**No behavior change holds.** The slice adds four things, and none of them changes an existing path:
- the `KINDS` row, which is inert as shown above;
- the installer row. Its copy step and its prune step are both no-ops for the new kind, as I read at `hos_install.sh:2146-2183`;
- the `KNOWN_LABELS` value, a classifier skip-list whose new entries appear in no agent file today;
- a CLI that nothing calls.

`dimension_registry_cli.py resolve --schema hos.label-registry` starts working as a side effect. That is harmless, and it is the engine's designed extension.

**The file cap holds: 14 of 15.** I accept both departures.
- **Adding `tests/automation/test_dimension_registry.py`: accepted, and required.** `:737` pins `registered_schemas() == (SCHEMA,)`. A second row cannot land without editing it. The new expected tuple is correct, because `registered_schemas()` sorts its output and `"hos.dimension-registry" < "hos.label-registry"`. My ADR file list missed this file. That is my error (§18.4).
- **Dropping `tests/framework/test_install_registry_data.py`: accepted.** The ADR listed it "only if T5.44 needs a fixture update". T5.44 compares the installer rows with `KINDS` as a set (`:159-166`), so it follows the new row on its own. The `.gitattributes` assertion at `:32` concerns `contract/dimensions/**` only, and S1 adds no installer `ensure_line`.

**What is correct, and what could still go wrong**, for the points §17 asked about:
- **§4.3 LR-10/LR-12 (the provider import named by data).** This is correct. It is confined to `scripts.automation.lib.*`, and `core.yaml` is CORE-only and protected. Residual risk: importing a module runs its import-time code. The defense is that the target set is reviewed first-party code. It is not a sandbox. Security-reviewer should confirm that no `scripts/automation/lib` module has import-time side effects beyond definitions.
- **§4.3 had one real defect, now fixed.** LR-2 type-checked `color` and returned `unknown_item_key`, which made LR-2's own `000000` → `bad_color` test unsatisfiable. I also pinned the evaluation order (§4.3, the "Evaluation order" paragraph).
- **§6.4 (`present-unprovisioned` does not change the exit code).** This is correct, and it is what ADR AD-7 says: exit 0 when everything is present, and existing labels are never modified. Residual risk: an auto-created label (VF-12) passes `check` silently, except in the report. That is acceptable. S3a's preflight exists to detect *missing* labels, and fixing a recoloured label would break the never-modify rule.
- **§8.3 (the unquoted-name heuristic).** This is correct as measured. P6's negatives cover the prose cases. Residual risk: a future unquoted single-word label such as `--label bug` in live code is dropped silently. `bug` has no hyphen, so the heuristic discards it. Today no live-code label lacks a hyphen except `wontfix`, which is quoted where it appears. I accept that risk for S1. If a hyphen-free label ever gets a live writer, the slice that adds it must quote it or add a shape.
- **§3.2 (spec-stage names as `planned` with `provision: false`).** This is correct. `planned` keeps P5 honest, because they have only `catalog` hits. `provision: false` stops a repo from presenting unimplemented labels as live. `hos-halt` as `active` with `provision: false` is also correct.

### 18.2 TD-ESC-1 ruling: the wrapper mints its own token (binding)

**Ruling: adopt the TD's default.** `bootstrap/provision_labels.sh` mints and revokes its own App token in the `pr_review.sh` shape. It adopts AD-1a's other rules: the interpreter ladder, no stdout, no JSON, no validating or defaulting of arguments, no added flags, pass-through exit codes, and not `exec`.

**Reasoning.** ADR-1643 §10.4 states AD-1a over `invoke_agent.sh` only, and it leaves the token-minting L3 family (`merge_authority.sh`, `pr_review.sh`) explicitly unamended. My ADR-1520 AD-7 phrase "per ADR-1643 AD-1/AD-1a" over-cited it. The intended meaning was the layering and the launch rules, not the no-mint clause.

The alternative fails on its own terms. Having L2 run `get_app_token.sh` and parse its `export` lines re-implements the sourced-file contract in Python. It would also put a live secret into a module whose audit record and stdout are serialised wholesale, which is a worse place for it.

AD-5 already prescribes the bash-mint pattern for the S6a sibling (`edit_issue.sh`). One rule for both tools is better than two.

**Binding condition added (§7.1 step 3a).** Unset `GH_TOKEN`, `GITHUB_TOKEN`, `HOS_BOT_LOGIN`, `HOS_EXPECTED_BOT_LOGIN` and `HOS_LABELS_TOKEN_MINT_FAILED` before the mint. Tests LW-8 and LW-9 enforce it.

I verified the defect this prevents in the precedent. `pr_review.sh`'s `revoke_token` calls `revoke_app_token.sh` unconditionally (`pr_review.sh:192`), and that script revokes whatever `GH_TOKEN` it inherits (`revoke_app_token.sh:43-53`). So on the no-mint and failed-mint paths, `pr_review.sh` revokes **its caller's** token. Copying that shape verbatim into a wrapper that S3a will call once per `bin/hos-cron` cycle would let a read-only preflight revoke the cycle's working token. The scrub also makes §7.3's claim true: the App mint becomes the only `GH_TOKEN` source.

**L2 grammar tightened to match L3's extraction (§6.1, LC-8).**
- Subcommand-first.
- Flags on the subparsers only.
- `allow_abbrev=False`.
- A repeated `--app` is a usage error.

With the scrub in place, a mismatch between the two layers can no longer reach ambient auth. The tightened grammar also keeps the audit's `app` field equal to the role that was minted.

**The ladder exit code `1` collides with `check`'s "missing" exit `1`.** I accept this. The ladder's `1` comes with empty stdout (ADR-1643 TD-D23 P0). L2's `1` always comes with a JSON document. S3a's preflight treats 1 and 2 the same way, as loud and non-halting. Any caller that must tell them apart checks whether stdout is empty.

**ADR-1643 §10.5 P0.** `labels_cli.py` has no module-level third-party import. PyYAML is reached only through the engine's lazy import, which surfaces as `registry:yaml_unavailable`, exit 2, a document with an `error`, and no claimed outcome. That satisfies P0's intent. The coder must keep every import of `labels_cli.py`, `label_registry.py`, `github.py` and `audit_log.py` at module level stdlib-only. Today all four are.

### 18.3 TD-ESC-2 ruling: the consumer shipping path (binding on the S6b TD; S1 unaffected)

**Ruling.** The S1 `_REGISTRY_KINDS` row is correct as designed. It is the pack-layer mirror and nothing more. **S6b owns every row that ships the labels kind to consumers.** S6b does **not** wait for #1643 W7.

**What S6b must ship:**
- `contract/labels/core.yaml`, through `framework_consumer_files.txt`, plus a `.hos-manifest` WHOLE row and an `ensure_line ".gitattributes" "contract/labels/** -text"`, so L31 holds;
- `scripts/automation/lib/label_registry.py`;
- `scripts/framework/labels_cli.py`;
- `bootstrap/provision_labels.sh`;
- the shared engine modules `scripts/automation/lib/dimension_registry.py` and `posture.py`, **if #1643 W7 has not already shipped them when S6b is coded**;
- the package markers `scripts/__init__.py`, `scripts/automation/__init__.py` and `scripts/automation/lib/__init__.py`. None of them is in `framework_consumer_files.txt` today, and without them the `scripts.automation.lib.*` imports fail in a consumer;
- `github.py` and `scripts/oversight/lib/audit_log.py`, unless the S6b TD shows they already reach consumers.

**If W7 lands first**, S6b adds only the label-specific rows. Either way, exactly one row per file ever exists. The S6b TD must re-check the list against `main` at the time it is written. `framework_consumer_files.txt:16`'s comment is about `run_post_change_sweep.sh`, and it stays withheld. Shipping the engine early does not ship the sweep.

**Why S6b does not wait for W7.**
- W7 is human-blocked on unrelated #1643 questions.
- AD-12 makes S6b part of the window-open release (H-3). Chaining H-3 to W7 would couple the label migration window to an unrelated escalation, and nothing technical needs it: the engine is stdlib plus lazily-loaded PyYAML.

**Two sequencing consequences, recorded for later slices:**
- **The S3a TD.** `bin/hos-cron` ships to consumers, and its S3a preflight will call `bootstrap/provision_labels.sh`. In a consumer that took S3a before S6b, that file is absent, so the call fails with exit 127. The S3a TD must classify any non-0/1/2 exit as "unprovisioned (tool unavailable)": loud, audited, non-halting, per AD-7. It must never treat that exit as success.
- **H-3** must carry S6b. AD-12 already requires this.

**Human input.** None new. Shipping files to consumers through the existing installer is the installer's ordinary job. The product-boundary item, the installer *mutating consumer GitHub state*, is already ARCH-ESC-1, which still blocks S6b.

### 18.4 Startup-gap recovery and affected sign-offs

*Should this have been settled in the initial architecture review?* **Yes, for all three items, and the gap is mine.** ADR-1520 has three misstatements:
1. **AD-7: "per ADR-1643 AD-1/AD-1a".** AD-1a's no-mint and no-argv clauses do not apply to a token-minting L3 (§18.2).
2. **AD-7 ("the installer ships it") and AD-10 step 1 ("`hos_install.sh` ships `contract/labels/` (S1's `_REGISTRY_KINDS` row)").** That row ships pack layers only (§18.3).
3. **§3, the S1 file list.** It omits `tests/automation/test_dimension_registry.py` (§18.1).

The generalisable rule is the same one ADR-1643 §10.6 recorded: **when an ADR cites a landed mechanism, it must state what that mechanism actually does, not what its name suggests.** I read `_REGISTRY_KINDS`'s comment ("Mirrors dimension_registry.KINDS") and not its loop body.

**Affected sign-offs.** No design or code has been built or approved against the superseded wording, except this TD, and this TD corrects all three items. **No sign-off is orphaned.** ADR-1520's acceptance stands, because no decision changes. These are corrections of fact and of citation. ADR §5's cross-ADR analysis (T3.0b, TD-1604, TD-1540 S2) is unaffected.

**Actions for the worker.** I am barred from GitHub and from editing other files in this task, so the worker does these:
- (a) Annotate #1520, or the existing `startup-artifact-gap` issue, with items 1-3 and the rule above.
- (b) In the S1 PR, or a docs follow-up, add an erratum note to ADR-1520 at AD-7, at AD-10 step 1 and at the §3 S1 row, each pointing to this §18.
- (c) File a follow-up issue: "`bootstrap/pr_review.sh` revokes the caller's inherited `GH_TOKEN` on its no-mint and failed-mint paths". The fix is §7.1 step 3a's scrub. Check `merge_authority.sh` and any other mint-in-wrapper for the same shape.

### 18.5 Reviewer set

§14 stands. Security-reviewer must check §7.1 step 3a, LW-8 and LW-9 specifically, as well as the LR-10/LR-12 import surface.
