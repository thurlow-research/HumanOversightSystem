# TECHNICAL DESIGN — #2062: reviewer-JSON extraction fails closed

Status: DRAFT, awaiting architect review. Follows #2032 (PR #2063) and #2036 (PR #2064).
Change class: **additive** (new extraction contract; `compute_verdict` unchanged).

RISK: MEDIUM. This changes what the verdict gate reads in four callers.
CONFIDENCE: HIGH for shapes 1–3. MEDIUM for the false-positive rate on real vendor prose (§6).

## Human Review Required
- Accept that review-key text the extractor cannot read now **blocks**, even in benign prose (§6, OQ-1).
- This is a one-PR security slice on a protected gate path.

## 1. Current behaviour (grounded)

- `_brace_objects` (`scripts/oversight/validation_logic.py:106-140`) uses plain `json.loads`, so the last duplicate key wins (L134). When a balanced span fails to parse it skips to `j+1` (L135-137). When a candidate is still unbalanced at EOF it sets `i=j+1=n+1`, which silently ends the scan and drops everything after the stray `{`.
- `extract_json_objects` (L143-160) works fence-first. If any ```` ```json ```` fence yields a block, the bare scan never runs (L158). The fenced predicate is verdict/findings/attacks. The bare predicate is findings/attacks only (L159). A top-level object is taken whole and never scanned inside, so `{"result":{...}}` is dropped.
- The docstring says the function "Mirrors validate_agents.sh's extract_objects exactly" (L149-150). That is **false**: `grep -rn extract_objects` finds only that docstring. No shell extractor exists any more.
- `compute_verdict` already counts one NEW, unsilenceable blocking finding for a `verdict:"error"` block (#670, L398-399). It does the same for malformed or basis-less blocks (#2032, L418-429).
- Callers:
  - `validate_agents.sh:460`, `validate_scripts.sh:263` and `run_second_review.sh:1082` call `process --strict-empty`.
  - `validate_self.sh:436-445` calls `extract_json_objects` directly and requires exactly one block. Any other count becomes a synthesized blocking document (L469-480).
  - In validate_agents/scripts the **raw** vendor stdout is embedded in a json fence (`validate_agents.sh:425-431`, `validate_scripts.sh:244`).
  - In run_second_review the fence holds the **salvaged** object, re-serialized by `_cmd_salvage`'s `json.dumps(found)` (`second_review_logic.py:1186`). It holds raw prose only when salvage returns None (`run_second_review.sh:829-833, 943-947`).

## 2. Design decision: one scan plus a residue rule (shapes 1, 2 and 3 share one mechanism)

### 2.1 Strict loader (new, public)
- `class DuplicateKeyError(ValueError)`.
- `loads_strict(s: str)` is `json.loads(s, object_pairs_hook=_reject_duplicate_keys)`. The hook builds the dict from the pairs and raises `DuplicateKeyError` on the first repeated key, at any nesting depth.
- Every parse inside the extractor uses `loads_strict`.

### 2.2 Review-shaped predicate and key pattern (new, module constants)
- `_is_review_dict(o)`: `isinstance(o, dict)` and the key set contains any of `verdict`, `findings`, `attacks`. This is a single predicate. It replaces the two divergent predicates at L156 and L159 and equals `second_review_logic._is_review_shaped` (L418-422).
- `REVIEW_KEY_RE = re.compile(r'"(?:verdict|findings|attacks)"\s*:', re.IGNORECASE)`.
- In valid JSON, text matching this pattern can only be an object **key**. A `"` inside a string value must be escaped as `\"`, which the pattern cannot match. So a match outside an accepted block means the reviewer wrote review-shaped JSON that the extractor did not read.

### 2.3 Scanner contract (`_scan(text) -> tuple[list[dict], str | None]`)
This replaces `_brace_objects` and the fence logic. **Fences are ignored.** The scan covers the whole text once. A fence's content is a substring of the text, so every fenced object is visited exactly once and no de-duplication is needed.

1. Walk `i` over `text`. At each `{`, run the existing string-aware depth walk (L116-138 semantics, unchanged).
2. **Balanced at `j`:** try `loads_strict(text[i:j+1])`.
   - If it parses to a dict, record `(span=(i, j+1), obj)` and set `i = j+1`.
   - On any exception (`DuplicateKeyError`, `JSONDecodeError`, `RecursionError`), set `i = j+1`. This matches today. The span is **not** masked (step 5).
3. **Unbalanced to EOF:** set `i = i+1`. This **changes** today's end-of-scan behaviour, so a stray prose `{` can no longer swallow the blocks after it.
4. **Work budget:** count every character step of the inner walk. Stop when the count exceeds `max(1_000_000, 64 * len(text))`. On exhaustion, return the blocks found so far and the reason `"scan-budget-exceeded"`. The budget bounds the O(n²) worst case that step 3 allows (for example 10⁵ unbalanced `{`).
5. **Accepted blocks** are the recorded objects with `_is_review_dict` true, in text order. **Residue** is `text` with each accepted span replaced by one space, so that tokens either side of a mask cannot join into a match. Parsed non-review objects are **not** masked.
6. The reason is `"unreadable-review-candidate"` if `REVIEW_KEY_RE.search(residue)` matches, otherwise `None`. The budget reason takes precedence.

### 2.4 `extract_json_objects(text) -> list[dict]` (public signature unchanged)
- Returns the accepted blocks.
- If `_scan` gave a reason, it appends **exactly one** synthetic block (never one per hit):
  `{"verdict": "error", "findings": [], "extraction_error": "<reason> (#2062)"}`.
- **Why `error` and not a #2032 malformed shape:** both reuse an existing branch that counts one NEW blocking finding which cannot be silenced (L398-399 vs L418-429). With `error`, `validate_self.sh` prints `verdict=error` instead of an opaque malformed value. It also matches the meaning of `--strict-empty` that `run_second_review.sh` documents (validation_logic.py L33-37): "a reviewer answered and we failed to read it." `compute_verdict` needs **no change**.
- New public helper `review_text_unreadable(text) -> bool` returns `_scan(text)[1] is not None`. It is used by second_review_logic (§4).
- Delete `_brace_objects`. The only references are in-module (grep confirms). Tests use only the public API.

### 2.5 How each shape resolves
| Shape | Input | Scanner outcome | Aggregate |
|---|---|---|---|
| 1 dup keys | `{"verdict":"request_changes","verdict":"approve","findings":[]}` | balanced, `DuplicateKeyError`, span left in residue, key hit | synthetic error → `request_changes` |
| 1b dup inside finding | `{"verdict":"request_changes","findings":[{"severity":"high","severity":"low",...}]}` | whole outer rejected (the hook fires at depth) | synthetic → `request_changes` |
| 2a bare block outside the fence | fenced approve + bare `request_changes` with a critical finding | both accepted | `request_changes` (real finding, ledger semantics kept) |
| 2b truncated | fenced approve + `{"verdict":"request_changes","findings":[{"sev…` to EOF | unbalanced, rescan, residue key hit | `request_changes` |
| 2c balanced unparseable | fenced approve + `{"verdict":"request_changes",}` | parse fails, residue hit | `request_changes` |
| 3 nested | `{"result":{"verdict":"request_changes","findings":null}}` (alone, or with an approve) | outer parsed but not review-shaped, so not masked; residue hit | `request_changes` |

**Shape 3 rule: detect, do not lift.** Nested review dicts are not promoted to blocks.
- Lifting would turn a lone nested *approve* from today's `error` (via `--strict-empty`) into `approve`. That loosens the gate, and no legitimate producer nests a review in a non-review object.
- Detection by residue does not depend on depth, so no recursion and **no depth bound** are needed. Deep nesting that `json.loads` cannot handle raises `RecursionError`, which falls under step 2's exception branch and leaves the span in residue.
- **No double counting:** an accepted review-shaped outer is one block, and its interior is masked. Children of a review-shaped outer are its content, not blocks.

### 2.6 Docstrings
- Rewrite the `extract_json_objects` docstring to describe §2.3–2.4.
- Remove the "Mirrors validate_agents.sh's extract_objects exactly" claim.
- Amend module binding 6 (L26-27) to say: "the shell extractor this binding named was removed; `extract_json_objects` is the sole implementation (#2062)."

## 3. Boundaries
- Shape 3 is **not** detected when the nested `request_changes` sits inside an accepted review-shaped outer, e.g. `{"verdict":"approve","findings":[],"x":{"verdict":"request_changes"}}`. The outer is authoritative, which matches salvage's `_is_review_shaped` early return (L527). This is recorded in the docstring as a known boundary (OQ-2).
- JSON inside string values is never parsed. Example: an agy envelope `response` given raw to validate_agents. This is unchanged.
- Verdict-inert sections (the #1718 advisory, ADR-2033 `[CONTEXT]`/`[COVERAGE]`) **must not** contain an unescaped review key. Today that is a convention (`run_second_review.sh:951-955`, ADR-2033 L485). After this change, breaking it fails closed instead of forging a verdict.
  - Update the comment at `run_second_review.sh:952-954`: "extract_json_objects scans the whole file, fences included; a stray review key here now gates (#2062)". This is a comment-only edit.

## 4. second_review_logic.py parity (changed in this PR, minimal)
It loads validation_logic via `_load_validation_logic()` (L177-190). Reuse it.
- **Shape 1: affected.** `_unwrap_envelope` (L535) and `salvage_with_metadata` (L750) both use `json.loads`, and `_cmd_salvage` re-serializes the result (L1186). So the duplicate collapses to `approve` **before** OUTFILE is written, and `process` can never see it.
  - **Change:** replace `json.loads` with `vl.loads_strict` at L535, L750 and L256.
  - At L535 and L750 the existing `except Exception: continue` covers the error, and the residue check below catches it.
  - At **L256 (`_aggregate_full`)** add `except vl.DuplicateKeyError:` **before** the generic handler. It appends `(name, "error", "none", 0, "json")` and continues. It must never reach `_classify_prose_full` (L258), whose `approve` keyword match reads attacker text.
- **Shape 2: affected at salvage.** A clean approve candidate plus a truncated or unparseable `request_changes` resolves to the approve, and the rest of the raw text is discarded.
  - **Change A**, in `salvage_with_metadata` after the resolution block (L782-794), only when a review was resolved (not the None return and not the ambiguous return): if `vl.review_text_unreadable(raw)`, return `_ambiguous_salvage_error("unreadable review-shaped JSON alongside the resolved review (#2062)"), metadata`.
  - **Change B**, in `_unwrap_envelope` after the candidate loop (L533-538): `if collected and vl.review_text_unreadable(response): return [_ambiguous_salvage_error("… inside envelope response (#2062)")]`. Envelope authority (L782) then makes the error authoritative.
  - Both guards apply **only when something was resolved**. A None result is left as None on purpose: raw text then reaches OUTFILE, and `process` gates it via §2. This keeps the pinned None tests valid (`test_truncated_response_still_yields_envelope_metadata_no_review`, `test_response_as_object_rather_than_string_is_not_unwrapped`, `test_response_string_with_unparseable_candidate_yields_no_review`, the status-gate tests).
- **Shape 3: alone, not applicable.** Salvage gives None, raw goes to OUTFILE, and `_aggregate_full` `json.loads` it. It has no verdict, findings or attacks, so the result is `error` (L296-297). **Combined with an approve, affected.** The single bare approve wins (L784). Change A covers it, because the `{"result":…}` span is unmasked residue.
- The envelope-escaped keys (`\"verdict\"`) in raw envelope text never match `REVIEW_KEY_RE`, so the decoy and envelope-authority tests are unaffected. Leave `_balanced_objects` (L388-415) unchanged.

## 5. Tests
New file `tests/oversight/test_validation_logic_extraction_2062.py`. Load the module by path as `test_validation_logic_request_changes_basis.py:19-28` does. Assert `compute_verdict(extract_json_objects(text), ledger)["verdict"]`, plus `process` CLI cases. `A` = `{"verdict":"approve","findings":[]}` and `RC` = `{"verdict":"request_changes","findings":[{"severity":"critical","files":["a"],"type":"x"}]}`, each in a ```` ```json ```` fence unless stated.

| Test | Input | Expected |
|---|---|---|
| `test_dup_key_verdict_blocks` | raw shape 1 | `request_changes`, `new_blocking_count==1`, one block carrying `extraction_error` |
| `test_dup_key_inside_finding_blocks` | shape 1b | `request_changes` |
| `test_dup_key_non_review_object_ignored` | `{"a":1,"a":2}` + fenced A | `approve` |
| `test_loads_strict_rejects_nested_dup` | `loads_strict('{"x":{"k":1,"k":2}}')` | raises `DuplicateKeyError` |
| `test_bare_rc_outside_fence_counts` | fenced A + bare RC | `request_changes`, two blocks |
| `test_truncated_rc_after_fenced_approve` | fenced A + bare truncated RC to EOF | `request_changes` |
| `test_unparseable_rc_after_fenced_approve` | fenced A + `{"verdict":"request_changes",}` | `request_changes` |
| `test_nested_envelope_alone` | shape 3 bare | `request_changes` (not empty, so `--strict-empty` is not needed) |
| `test_nested_envelope_plus_approve` | shape 3 + fenced A | `request_changes` |
| `test_nested_approve_alone_not_lifted` | `{"result":A}` | `request_changes` (detect, do not lift) |
| `test_stray_unbalanced_brace_before_fence` | `prose { oops` + fenced A | `approve` (rescan) |
| `test_prose_braces_without_keys` | `` `${HOME}` and {x} `` + fenced A | `approve` |
| `test_escaped_key_in_string_value` | A whose summary is `say \"verdict\": no` | `approve` |
| `test_schema_echo_fails_closed` | fenced A + `{"verdict":"approve|request_changes","findings":[...]}` | `request_changes` (deliberate, §6) |
| `test_one_synthetic_block_per_text` | three unreadable candidates | exactly one `extraction_error` block |
| `test_scan_budget_fails_closed` | `"{" * 200_000` + fenced A | ends; one block with `scan-budget-exceeded`; `request_changes` |
| `test_chunked_adr2033_multi_block` | 4 fenced A + a plain-fence `[COVERAGE]` text with no keys | `approve`; plus one fenced RC → `request_changes` |
| `test_ledgered_rc_still_converges` | fenced RC + ledger `fixed` for its fingerprint | `approve` (#2036 / #2032 parity) |
| `test_cli_process_strict_empty_dup_key` | `main(["process",…,"--strict-empty"])` on an OUTFILE with shape 1 | header `verdict: request_changes` |
| `test_validate_self_single_doc_unchanged` | one `json.dumps` of an invoke_agent-style doc with nested `input`/`observability` dicts | exactly 1 block, no `extraction_error` |

New file `tests/oversight/test_second_review_extraction_2062.py`:
| Test | Input | Expected |
|---|---|---|
| `test_salvage_dup_key_alone_is_none` | raw shape 1 | `salvage_review_json(raw) is None` |
| `test_salvage_approve_plus_dup_rc_errors` | A + dup-key RC | verdict `error` |
| `test_salvage_approve_plus_truncated_rc_errors` | A + truncated RC | verdict `error` |
| `test_salvage_approve_plus_nested_rc_errors` | A + shape 3 | verdict `error` |
| `test_envelope_response_approve_plus_truncated_rc_errors` | `{"status":"SUCCESS","response": A + truncated RC}` | verdict `error` |
| `test_aggregate_dup_key_body_is_error_not_prose` | `## agy` section, body = raw shape 1 | `aggregate_verdicts(...)["verdict"] == "error"` |
| `test_plain_and_fenced_review_unchanged` | A; fenced A | equal to A |

**Non-regression:** run all of `tests/oversight/`. In particular, the files below must pass **unchanged**:
- `test_validation_logic.py`, including `test_extract_malformed_json_skipped`, because `{not valid json,,,}` has no quoted key;
- `test_validation_logic_request_changes_basis.py`;
- `test_second_review_envelope_salvage.py`;
- `test_second_review_logic.py` (`test_2036_*`);
- `test_vendor_prompt_consumption_guard.py:601-626`;
- `tests/framework/test_agent_invocation_migration.py`.

If an existing test relies on fence-first masking, it is asserting the bug. The coder updates it and lists it in the PR body. The coder does not change the design to keep it.

## 6. False-positive analysis (accepted, fail-closed direction)
A legitimate output now blocks only when unescaped `"verdict"/"findings"/"attacks":` text sits outside an accepted block. That means:
- a schema echo containing invalid JSON;
- a balanced, unparseable review in prose braces;
- review keys quoted in prose.

The prompts' schema examples are valid JSON (`validate_scripts.sh:199-200`). A parseable echo is already blocking under #2032, because its verdict is `approve|request_changes`. So this does not newly block on typical echoes.

An unreadable-residue block is unsilenceable, so a lane that persistently produces one cannot converge. It reaches a human, the same as #670.

## 7. Slice: one PR, 6 files (cap 15)
1. `scripts/oversight/validation_logic.py`
2. `scripts/oversight/second_review_logic.py`
3. `scripts/run_second_review.sh` (comment at L952-954 only)
4. `tests/oversight/test_validation_logic_extraction_2062.py` (new)
5. `tests/oversight/test_second_review_extraction_2062.py` (new)
6. this design document

Add the prompt artifact per repo convention. No change to `compute_verdict`, `validate_*.sh` or `agent_invoke_cli.py`.

## 8. Startup-gap and affected sign-offs
Should this have been settled up front? Yes. #2032's design fixed `compute_verdict` but did not cover the extractor that feeds it. A `startup-artifact-gap` annotation on #2062 is recommended. This design session does not file it.
- Sign-offs for #2032 (PR #2063) **stand**: the `compute_verdict` contract is unchanged.
- Sign-offs for #2036 (PR #2064) **stand** for ledger semantics. The new `DuplicateKeyError` branch at L256 is new code and is reviewed in this PR.
- No approved code is orphaned.

## 9. Open questions for architect or human
- **OQ-1 (architect):** Accept §6. Balanced-unparseable and quoted review keys in prose fail closed, and an unreadable residue can never be ledgered to convergence.
- **OQ-2 (architect):** Accept the §3 boundary that nested review keys inside an accepted review-shaped outer are not inspected.
- **Observation, outside scope:** `_unwrap_envelope`'s status gate (L524-526) drops a review-shaped `{"status":"ERROR","verdict":"request_changes",…}` candidate. If a bare approve sits next to it, salvage returns approve (L784). This is a fourth masking shape that predates #2062. A follow-up issue is recommended. It is not fixed here.
