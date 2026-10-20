# ADR-2101: The human authorizes a gated step with one prescribed-form GitHub comment. One protected, shipped verifier decides, with no network inside the predicate. It binds the act to a whitespace-exact patch-id of the step's own diff, refuses every bot and every edited comment, reads CODEOWNERS from the server's default branch, and audits every verdict. The clone file is retired as authority

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-4, AD-6, AD-9 and AD-10 bind `technical-design`. AD-5, AD-7 and AD-8 are **PROVISIONAL**: each is drafted on the recommended option and names what changes under the alternative. REQ-2 (no bot, including the human-proxy, ever authorizes) and REQ-9 (fail closed) are not open to any ESC answer or agent-side waiver.
**Date:** 2026-10-15
**Author:** architect (autonomous worker cycle; no human present)
**Issue:** #2101 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** Every slice lands on protected surface: `scripts/framework/**` (`protected_surfaces.txt`), `.claude/agents/**` and `contract/**`. The human gate therefore applies whatever tier is computed.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2101-github-native-human-authorization.md` (VF-1 to VF-6, REQ-1 to REQ-13, ESC-1 to ESC-5). Also `scripts/framework/require_human_approval.py:140-172`, `scripts/framework/requester_trust.py:10-15,242-326,449-477,614-647`, `scripts/automation/lib/merge_authority.py:44-64,713-733`, `scripts/automation/lib/pr_readiness.py:113-114,484-492`, `scripts/automation/lib/github.py`, `scripts/oversight/lib/audit_log.py:126,206-235`, `bootstrap/escalate_to_human.sh:111-112,213-228`, `.claude/agents/oversight-evaluator.md:35,121,130,148-155,198-219,425-433,566,588,706`, `.claude/agents/oversight-orchestrator.md:344-361`, `.claude/agents/risk-assessor.md:226-239`, `contract/OVERSIGHT-CONTRACT.md:77-89,424,436,541-551,573-584`, `docs/v0.7.0/ADR-1913-…` (AD-6), `docs/v0.7.0/ADR-1928-…` (AD-8, AD-9, S3).
**Consumers:** `technical-design` → `coder` → review chain. `security-reviewer` is mandatory on S1 and S2 (the verifier is the trust decision for the hardest human gate). `privacy-reviewer` is mandatory on S1 (new login- and URL-bearing audit events). The `.claude/agents/**` edits in S2 and S3 are authored by the top-level session, never by `coder` (CLAUDE.md, #1347).
**Explicitly does NOT re-litigate:** when conditions 7 and 10 fire; #757's merge-time approval; NG3b; `is_bot_reviewer`'s layering; SPEC-267's canonicalization rule; tier overrides and gate suspension; #1928's summoning mechanism; #1936's team expansion; #2031's classifier.

---

## 0. Verification findings (working tree at `3194b6a2b`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** `pr_readiness.py:113-114` (`_human_authorization_path`) and `:484-492` (`_check_critical_human_authorization`: presence and non-emptiness only). Evaluator references at `:35`, `:121`, `:130`, `:148-155`, `:198-216`, `:219`, `:425-433`, `:566`, `:588`, `:706`. Orchestrator instruction at `:344-361`. Contract `:77-89`, `:541`, `:551`.
- **VF-3, VF-4 accepted as stated.** Nothing in this ADR depends on them except the conclusion, which I share: the file proves nothing about who wrote it.
- **VF-5 CONFIRMED, with one correction (AF-3).**
  - `is_bot_reviewer(login, user_type, bot_accounts)` is at `require_human_approval.py:140`.
  - `codeowners_humans` at `requester_trust.py:263`, `load_bot_accounts` at `:301` and `verify_codeowner_actor` at `:614` all exist as cited.
  - `_find_human_approval` is at `merge_authority.py:44`. It matches a single configured login by equality, not through `is_bot_reviewer`.
  - `audit_log.write_event` is at `audit_log.py:126`, and its CLI `write [root]` takes event JSON on stdin (`:206-235`).
- **VF-6 accepted.** I adopt SPEC-328 R2.5's shape ("the GitHub record is the authorization record") and reject its C3 actor rule, as pm-agent does.

### 0.2 Architect findings (these change the design)

**AF-1 (HIGH): the act must work before a PR exists, so it cannot be a PR approval.** #1776, #1968 and #1988 are local-only. They are stopped by an evaluator ESCALATE that `pr_readiness` REQ-W-13/14 turns into a refusal to open the PR (VF-2). Under ESC-1(B) the evaluator would have to return CONDITIONAL_PROCEED with an unmet hard gate. That converts the CRITICAL gate from "before the outer loop" into "before merge", and it depends on #1913's unbuilt `evaluation_verdict.py` (it does not exist on this tree). A comment on the step's **issue** exists in every state the stuck steps are in. AD-1 chooses it.

**AF-2 (HIGH): CODEOWNERS read from the working tree is attacker-controlled input.** `codeowners_humans(repo_root)` reads `.github/CODEOWNERS` from disk. The evaluator runs in the author's clone, on the author's branch. A bot cannot pass `is_bot_reviewer` itself, but a branch that adds an arbitrary human account to CODEOWNERS widens the accepted set, and the protected-surface gate only stops that at merge, after the verifier has already said yes. AD-3 reads CODEOWNERS from the **server's default branch** through the contents API. Only the denylist may take a local contribution, and only by union.

**AF-3 (HIGH): the verifier must not import `scripts/automation/**`, so `github.py` is not reused.** `requester_trust.py:10-15` binds "MUST NOT import from scripts/automation/** or scripts/oversight/** — those are not protected surfaces". ADR-1928 AF-4 and `select_work_candidates.py` made the same choice. The brief's suggestion of reads "via `scripts/automation/lib/github.py`" would let an overseer-only PR change what the verifier sees, so I reject it. The verifier gets its own bounded `gh api` fetcher, on the `requester_trust._run_gh_get` model (one `gh api` GET per page, no `--paginate`, a 30 s subprocess timeout). Audit goes through `audit_log`'s **CLI as a subprocess**, after the decision is computed. An in-process load of an unprotected module could monkeypatch the verdict. A subprocess can at worst corrupt the record.

**AF-4 (HIGH): an App with `issues: write` can edit a human's comment.** Edit detection is therefore a forgery control, not a hygiene rule. Without it, a bot could rewrite the binding, the items or `reviewed_files:` under a genuine CODEOWNER's authorship. AD-4 refuses any comment whose body has changed since creation.

**AF-5 (MEDIUM): the pre-PR verdict runs code the author can edit. The merge-time re-check is the anchor.** The evaluator and `pr_readiness` run the verifier from the worker clone on the step branch. A step whose diff weakens `scripts/framework/human_authorization.py` gets a weakened pre-PR verdict. That step touches `scripts/framework/**`, so it is protected-surface and needs the human's PR approval anyway. The overseer runs from its own default-branch checkout. AD-6 therefore makes the overseer's re-verification the anchor: it can only add HUMAN_REQUIRED. This is R-3 of ADR-2100, restated rather than widened.

**AF-6 (MEDIUM): `git patch-id` ignores whitespace by default.** In Python, YAML or Makefiles a whitespace-only commit after the act changes behaviour. The binding uses `git patch-id --verbatim` (git 2.53.0 on this machine) with every diff option pinned (AD-5).

**AF-7 (MEDIUM): "postdates the request" adds a dependency and no safety.** The binding is a content-derived nonce, so an act cannot name content that did not yet exist. Requiring the act to postdate a bot-authored request comment would make a bot's comment part of the trust chain. That is safe in direction (a later request can only make an act stale), but it blocks a human who authorizes from the pre-filled block before the request is posted. I amend REQ-4 (AM-1).

**AF-8 (LOW): the domain structural-auth files have the same defect.** `oversight-evaluator.md:219` and `:431` accept `.claudetmp/oversight/step{N}-<domain>-structural-auth.md`, "written by a human", as cover for a structural signal. If the main file loses authority and these keep it, condition 10 keeps an unverifiable bypass. AD-7 retires them together.

**Reuse search (CLAUDE.md item 1).** I searched `scripts/`, `bootstrap/`, `bin/` and `scripts/automation/lib/` for a comment-act verifier, a diff-content binder, a CODEOWNERS reader at a ref, and an audit writer.
- Found: `is_bot_reviewer`, `codeowners_humans`, `load_bot_accounts` and the `verify_codeowner_actor` pure-predicate pattern. All are reused (AD-2, AD-3).
- Found: the `escalate_to_human.sh:221-228` own-comment rule (`updated_at == created_at`). AD-4 reuses it.
- Found: `audit_log` CLI (AF-3).
- Found nothing that parses a human-typed form, computes a step binding, or reads a file at the server's default branch.

---

## 1. Organizing principle

**GitHub holds the authorization. One protected script reads it, and every consumer asks that script.** The act is a comment whose GitHub-reported author is a verified individual human CODEOWNER, whose body is byte-identical to what was posted, and which names this step, this exact content and the items it covers. Nothing in a clone confers authority: no file, no cache, no derived record. Every verdict, positive or negative, is computed fresh from live reads and recorded. Anything the script cannot establish is "not authorized".

---

## 2. Decisions

### AD-1: The authorizing act is a prescribed-form issue comment by a verified human CODEOWNER, on the step's issue or its PR. PR approval is not an authorizing act in v1. (BINDING on mechanism; ESC-1(A); REQ-1, AF-1.)

- **Where.** An issue comment on the step's own issue, or a conversation comment on the step's PR. Both are `/issues/{n}/comments` in REST, so there is one read path. PR **review** bodies are not accepted in v1: the review object has no reliable edit signal in REST (AD-4), and accepting it adds a second parse and fetch path for no case the stuck steps need.
- **Form (fields binding; exact grammar is `technical-design`'s, generated and parsed by one module, AD-2).** The first non-blank line is the form marker:
  ```
  /hos authorize step=<N> binding=patch:<40-hex>
  covers: C7 C10:<signal> BF:<finding-id>
  reviewed_files:
    - <path>
  ```
  A decline is `/hos decline step=<N>`. It carries no binding and applies to the step regardless of content.
- **Strictness.**
  - A comment whose first non-blank line starts with `/hos authorize` or `/hos decline` is a **candidate**.
  - A candidate that does not parse is `malformed`. That covers an unknown key, a duplicate key, a missing field, a binding that is not 40 hex, an empty `covers:`, or a second marker line.
  - Any other comment is ignored and produces no event.
  - Free text is allowed only after a line consisting of `---`.
- **Why not a label or a reaction.** Neither carries the binding, the items or `reviewed_files:`. A label is also a write that bots perform routinely, and NG3b already gives labels a separate meaning.
- **NG3b separation.** The marker shares no prefix with NG3b's `Authorization required:`/`Release candidate SHA:` lines. A test pins that the verifier refuses an NG3b release comment and that the NG3b checker ignores a `/hos authorize` comment.
- **#757 is unchanged.** After the PR opens, merge still needs the human's approval on the head SHA. For a gated step the human therefore makes two acts, the comment pre-PR and the approval at merge, which is the same count as today (file plus approval).
- **Under ESC-1(C).** Add the AD-6 rule that a CONDITIONAL_PROCEED PR whose only unmet items are `C10:*`, on a non-CRITICAL step, is satisfied by `_find_human_approval` on the head plus a review body carrying `reviewed_files:` (ESC-2's default). That requires #1913 S-slices first and a GraphQL edit check for review bodies. It is a separate slice (S4′), not part of this ADR's plan.

### AD-2: One verifier, `scripts/framework/human_authorization.py`, protected and shipped. A pure predicate, a separate bounded fetcher, a CLI with a fixed exit contract. (BINDING; REQ-3, D41, AF-3.)

- **Module layout.**
  - `parse_act(body) -> Act | ParseError`, and `render_request(step, binding, items, diff_files) -> str`. Both live in one module so the form cannot drift between the text the human is given and the text the verifier accepts. A round-trip test pins it.
  - `decide(acts, codeowners, bots, step, binding, required_items, diff_files) -> Verdict`. Pure: no I/O, no clock, no environment. It is modelled on `verify_codeowner_actor`.
  - `compute_binding(repo_root, base, head) -> str` (AD-5). Local git only.
  - `fetch(...)`. All GitHub reads, bounded, fail-closed (AD-3).
- **Permitted imports:** the standard library, `scripts.framework.require_human_approval.is_bot_reviewer`, and `scripts.framework.requester_trust`'s public functions. Nothing from `scripts/automation/**` or `scripts/oversight/**`. An import-graph test pins this, as for `requester_trust`.
- **CLI.**
  - `verify --repo <owner/repo> --step N --issue N [--pr N] --base <ref> --head <sha> --require <item>[,<item>…] --consumer evaluator|pr-readiness|overseer [--json]`.
  - `binding --base <ref> --head <sha>` prints the binding.
  - `render-request …` prints the AD-9 block.
- **Exit contract (`verify`).**
  - 0: every required item is covered by the governing act.
  - 1: not authorized, decided on complete data (no act, declined, stale, uncovered items, and so on).
  - 2: usage error.
  - 3: could not decide (API error, timeout, rate limit, pagination bound, unreadable or empty CODEOWNERS humans set, git failure).
  - 4: the decision was "authorized" but the acceptance audit write failed, so the result is **not authorized** (REQ-10 makes an unrecorded acceptance impossible).

  **Every consumer treats any non-zero exit as "not authorized".** Only 0 clears an item.
- **JSON output (stdout).** `{verdict, covered[], unmet[], binding, act:{id,url,login,type,created_at,content_sha256}|null, refusals:[{id,url,login,reason}], error|null}`. Consumers quote it in their reports. They never re-derive it.
- **Shipped.** Added to `framework_consumer_files.txt` in S1. Consumers already receive `require_human_approval.py` (`:81`) and `requester_trust.py` (`:97`).

### AD-3: Actor rule. A verified individual human CODEOWNER from the default branch, no bot by any layer, identity from the payload only. (BINDING; REQ-2, AF-2. Not open to any ESC.)

An act counts only if **all** of the following hold:
1. `comment.user.login` (from the API payload, never from the body) is in the **default-branch** CODEOWNERS humans set.
   - That set is fetched as `GET /repos/{o}/{r}/contents/.github/CODEOWNERS?ref=<default_branch>` and parsed by `parse_codeowners_humans(text)`.
   - `parse_codeowners_humans` is a refactor that extracts `codeowners_humans`'s loop (`requester_trust.py:263-282`) into a text-taking function. Its behaviour is byte-identical, and the existing tests pin it.
   - Teams are skipped (#1936).
   - The working-tree CODEOWNERS is **never** consulted for acceptance (AF-2).
2. `is_bot_reviewer(login, user.type, bots)` is false, where `bots = load_bot_accounts(local) ∪ baseline(default-branch machine-accounts.env)`. The union can only widen the denylist. This refuses the human-proxy App (`[bot]` suffix, `BOT_HUMAN_USERNAME`), the worker, the overseer, Copilot, any App by `type == Bot`, and any PAT machine user in `BOT_ACCOUNTS`.
3. Case-insensitive login comparison, as in both reused functions.

An empty CODEOWNERS humans set, an unreadable default-branch file, or any read error gives exit 3. **Fetch bounds:** comments are read at `per_page=100` with an explicit page loop and a hard cap (`technical-design` sets it; I suggest 10 pages). Reaching the cap without a short page gives exit 3 `pagination-bound`. The verifier never decides on a partial list.

### AD-4: Validity. Unedited, undeleted, live on every call. The latest qualifying act governs. (BINDING; REQ-4, REQ-8, AF-4, AF-7.)

- **Unedited.** The verifier requires `updated_at == created_at` on the REST comment. This is the `escalate_to_human.sh:226` rule. If it is false, the refusal is `edited`.
  - **Direction.** If GitHub bumps `updated_at` for something other than a body edit, the error is an over-refusal: the human posts a new comment. If an edit could ever leave `updated_at` unchanged, that would be an under-refusal, and nothing suggests it can.
  - **S1 obligation.** `technical-design` probes the live API once (edit a comment, and add a reaction to another) and records the result in `research/findings/api-field-shape-verification.md`. If reactions bump `updated_at`, it may add GraphQL `lastEditedAt == null` as an **alternative pass condition** (accept when `lastEditedAt` is null even if `updated_at` moved), but only with a fail-closed fetch. It must never be a replacement that weakens the REST rule's direction on edits.
- **Undeleted and live.** Every `verify` call re-reads the comment list. A deleted comment is simply absent. Nothing is cached across calls or written to disk (AD-7).
- **Placement.** Only comments on `--issue` and, if given, `--pr` are read. The form's `step=` must equal `--step` (`wrong-step` otherwise). Cross-PR replay is harmless because step and binding must both match.
- **Freshness (AM-1).** The binding is the freshness control (AD-5). An act whose binding differs from the computed one is refused as `stale`. No dependency on a bot-authored request comment.
- **Supersession.**
  - Acts by verified CODEOWNERS are ordered by `created_at`, with ties broken by comment `id` (monotonic), so the order is always determinable.
  - The **latest** qualifying act governs.
  - A decline governs over every earlier authorize for the step, whatever their bindings.
  - An authorize posted after a decline governs if it names the current binding.
  - A malformed candidate by a verified CODEOWNER that is newer than the governing act makes the result exit 1 `malformed-latest`, with the parse error in `refusals[]`. A human's newest word must never be silently skipped.
  - Malformed or refused candidates by non-CODEOWNERS or bots are recorded and ignored.

### AD-5: Content binding is a whitespace-exact patch-id of the step's own diff, computed with pinned options. A pure merge from base keeps it. Any other change voids it. (PROVISIONAL on ESC-3 default; REQ-5, AF-6.)

- **Definition.** `binding = patch:` + `git patch-id --verbatim` over `git -c diff.algorithm=myers -c core.quotePath=true diff --no-ext-diff --no-textconv --no-color --no-renames --full-index --binary <merge-base(base, head)> <head>`.
  - `base` is the default branch's remote-tracking ref for the evaluator and `pr_readiness`, and the PR's base SHA for the overseer.
  - The pinned options make worker and overseer clones agree whatever their local git configuration. A test runs the computation under a hostile `.gitconfig` (a different `diff.algorithm`, `diff.renames=copies`, a textconv driver) and asserts the same id.
- **Effect.**
  - A merge from `main` that leaves the step's own changes identical keeps the binding, which is what #1968 and #1988 need.
  - A conflict resolution, any new step commit, or a whitespace-only change voids it.
  - A change in `main` to context lines adjacent to the step's hunks also voids it. That is an over-refusal, accepted and stated (R-2).
- **The diff's file list** (`git diff --name-only`, same options and range) is the SPEC-267 coverage universe (AD-8).
- **Under the stricter ESC-3 alternative.** `binding = head:<sha>`. The same field is used and only `compute_binding` changes. Every merge from base then needs a fresh act.

### AD-6: Consumers. The evaluator, `pr_readiness` REQ-W-07 and the overseer call `verify`. The overseer's call runs from its own default-branch checkout and can only raise its decision. (BINDING; REQ-3, AF-5.)

- **Evaluator.**
  - Condition 7 calls `verify --require C7 --consumer evaluator`.
  - Condition 10 and condition 14's reused skip call it with `--require C10:<signal>…`, one item per detected signal. A per-signal list is stricter than today, where the file's mere existence covered every signal. The pre-filled block lists the signals, so it costs the human nothing.
  - 7b `escalated:` resolutions call `--require BF:<id>` (AD-8).
  - These can be one call with the union of items, and the verdict is split per item from `covered[]`.
  - The prose cites the script's JSON and may not substitute its own reading of comments.
- **`pr_readiness.py` REQ-W-07.** `_check_critical_human_authorization` becomes a subprocess call to `verify --require C7 --consumer pr-readiness`. Exit 0 means pass. Any other exit fails, with the JSON's `unmet` and `error` in the message. `_human_authorization_path` is deleted.
- **Overseer.**
  - For a PR whose committed evaluation artifact, or the evaluator report quoted in the PR body, names gated items, the overseer runs `verify` from **its own clone at the default branch** (`--base` = PR base SHA, `--head` = PR head SHA) before any approve or merge decision.
  - Non-zero means HUMAN_REQUIRED with `needs-human` and a reason that names the verifier result.
  - This only adds a gate. It never clears #757 or any other gate.
  - It catches a decline, an edit or a deletion that happens after the PR opened.
- **Audit volume.** The evaluator and `pr_readiness` audit every verdict. The overseer passes `--audit-on-change`, which writes only when the verdict for (step, binding) differs from that clone's last recorded overseer verdict. `technical-design` chooses the local record. It may only suppress a write, never alter a verdict.

### AD-7: The file artifact is retired as an input. No derived record is written. The domain structural-auth files are retired with it. (PROVISIONAL on ESC-5; I disagree with the default (ii). REQ-11, AF-8.)

- **Retired.** No code or agent reads `.claudetmp/oversight/step{N}-human-authorization.md` or `.claudetmp/oversight/step{N}-*-structural-auth.md` as authority for conditions 7, 7b, 10 or 14, or for the `:121` brownfield fallback. If such a file is present, the evaluator records INFO `legacy-auth-file-ignored` and names the GitHub act instead. That makes the transition legible to a human who still writes one.
- **Why not (ii), a derived record.**
  1. The path has carried authority in every agent and contract text since SPEC-267. A file at the same path that "must never be read as authority" is the most likely regression site in the system, and a grep test cannot tell a forbidden read from a permitted one.
  2. Every reader that (ii) is meant to keep informative (the evaluator report, `pr_readiness` messages) gets more information from the verifier's JSON, which is live.
  3. A bot-written derived file reopens the SPEC-82 question that REQ-11 asks to avoid.
  4. Under (i), the record is the GitHub comment plus the `human-authorization` audit event, which is SPEC-328 R2.5's shape exactly.
- **SPEC-82.** `step{N}-human-authorization.md` and the domain structural-auth files are removed from the evaluator's governance-artifact list (`:566`, `:588`, `:706`). The bot-commit check stays for the committed artifacts (`contract/gate-suspension.md`, `contract/tier-overrides/…`). The control for authorization is re-verification (AD-4), not authorship of a file.
- **The `:121` brownfield fallback** becomes item `RA-FALLBACK`, authorized by the same act.
- **Out of scope, routed (N-2).** The legacy `.claudetmp/oversight/human-tier-override.md` accepted at `:431-433` has the same VF-3 defect. Tier overrides are a §3 non-goal, so it is not changed here.
- **Under (ii).** S2 adds a writer in the verifier (`--write-record`, gitignored, never committed) and a grep test that only the verifier writes the path. AD-7's legacy INFO becomes "record present". **Under (iii)**, rejected: it preserves VF-3's unverifiable path. I would not accept it without a new threat model.

### AD-8: Coverage and items. SPEC-267 overlap is required for every authorize act. Items are closed-set and named. (BINDING on rule; PROVISIONAL on `BF:` scope, ESC-4. REQ-6, REQ-7.)

- **`reviewed_files:`** is required in every `authorize` act, not only for condition 10. Today contract §1 already lists it as a required field of the file. At least one entry must be in the AD-5 file list, under SPEC-267 canonicalization: exact match, case sensitive, a single leading `./` stripped, no prefix or basename matching. An act that is empty, absent or wholly non-overlapping is refused as `no-overlap`, and all of its items stay unmet. The parser and matcher port `oversight-evaluator.md:204-216` exactly. A table test reuses SPEC-267's fixtures.
- **Item set (closed; anything else is `malformed`):**
  - `C7`;
  - `C10:<signal>`, with signal names taken from `change_classifier.py`'s enum, not from this ADR;
  - `BF:<id>`, a `blocking_findings` id (`risk-assessor.md:229`, short-kebab);
  - `RA-FALLBACK`.
- **An item the act does not name stays unmet** (REQ-7 AC).
- **`BF:` resolution form.** `risk-assessor` records `resolution: escalated: github-act`, and the evaluator clears it only on `covered ∋ BF:<id>`.
  - **Residual R-4.** The id is agent-chosen. An agent could re-describe a different finding under an id the human already authorized. The pre-filled block quotes each finding's `source` and `description`, and the act does not bind them.
  - **Rejected for v1:** hashing the finding text into the item. It would make every risk-assessor re-run, which rewrites prose, void the act.
- **Under ESC-4 "no".** `BF:` is removed from the set, and #1776 stays blocked on its dep-mapper finding until the human installs an override or suspends dep-mapper. That is today's `risk-assessor.md:132` remedy.

### AD-9: Escalation names the act, rendered by the verifier, posted on the step's issue. No clone path appears in any human-facing authorization text. (BINDING; REQ-12, REQ-13.)

- **Content.** `render-request` produces a block in #1928 REQ-A1 / ADR-1928 AD-8 shape:
  - `### Action needed`
  - `Action:` "post this comment" followed by the fenced, pre-filled form: step, current binding, every required item, and the full diff file list under `reviewed_files:` for the human to prune. It is followed by each `BF:` finding's source and description, and the alternative `/hos decline step=<N>`.
  - `Where:` the step issue URL (and the PR URL if one exists).
  - `Who:` "the human CODEOWNER, from your own GitHub account; the human-proxy session cannot do this".
  - `Done when:` "the next evaluator run reports the items covered".
- **Delivery.** The worker posts the block through `bootstrap/escalate_to_human.sh` with `--body-file`, so there is no new filer. The verifier never posts.
- **#1928 sequencing.**
  - The block is valid whether or not #1928 S3's refusal has landed, so there is no hard dependency.
  - #1928 S3 and this ADR's S3 both edit `worker.md`'s escalation text (`:171-177`). Whichever lands second rebases.
  - The rendered text contains none of ADR-1928 AD-9's forbidden strings, so the attention pass can quote it. A test pins that.
- **Grep test.** No orchestrator, worker, evaluator, runbook or contract block addressed to the human names `.claudetmp/` or `-human-authorization.md`, or tells the human to create, edit or commit a file to authorize. The heredoc at `OVERSIGHT-RUNBOOK.md:560-571` is deleted.

### AD-10: Audit. Every candidate verdict is recorded through the `audit_log` CLI as a subprocess, after the decision. (BINDING; REQ-10, AF-3.)

- **`human-authorization`** (an existing §6a event, extended compatibly).
  - The existing fields keep their names. `artifact` becomes the comment URL. `authorized_by` becomes the verified login. `content_sha256` is the sha256 of the comment body as returned. `decision` stays.
  - Added fields: `source=issue-comment`, `comment_id`, `actor_type`, `step`, `binding`, `covered`, `reviewed_files`, `consumer` and `verified_at`.
- **`human-authorization-refused`** (new). It carries `step`, `binding`, `comment_id`, `url`, `login`, `actor_type`, `consumer` and a closed `reason`: `bot-actor`, `not-codeowner`, `edited`, `stale`, `wrong-step`, `no-overlap`, `malformed`, `malformed-latest`, `declined` or `api-failure`. One event is written per refused candidate. An `api-failure` event carries no comment fields.
- **Order and failure.** The verdict is computed first. Then `python3 -m scripts.oversight.lib.audit_log write <root>` runs, with the event JSON on stdin. An acceptance whose write fails gives exit 4 (not authorized). A refusal whose write fails stays a refusal, with a stderr WARN.
- **Privacy.** Logins, comment URLs and the body hash are all public on GitHub already. The body itself is **not** logged, because only its hash is needed. This is `privacy-reviewer`'s to confirm on S1.

---

## 3. Failure modes

| Failure | Behaviour | Direction |
|---|---|---|
| API error, timeout, rate limit, pagination cap | exit 3, `api-failure` event, ESCALATE | Closed |
| Default-branch CODEOWNERS unreadable or humans set empty | exit 3 | Closed |
| `git` fails computing the binding (missing base, shallow clone) | exit 3 | Closed |
| Comment edited by anyone, including a bot | `edited` | Closed |
| Comment deleted after acceptance | Absent on the next call, so unmet | Closed |
| Human-proxy relays the ruling | `bot-actor` | Closed |
| Branch adds a human to CODEOWNERS | Ignored: only the default-branch set counts | Closed |
| New step commit, or a whitespace-only change | `stale` | Closed |
| Merge from main with conflict resolution | `stale`, so a fresh act is needed | Closed (over-refusal) |
| Acceptance audit write fails | exit 4, not authorized | Closed |
| Step diff weakens the verifier | Pre-PR verdict untrusted. Protected-surface gate plus overseer default-branch re-check | Anchored at merge (AF-5) |
| Legacy hand-written file present | INFO `legacy-auth-file-ignored`, no authority | Closed |

**Residuals (stated, not hidden).**
- **R-1.** `reviewed_files:` proves that the human left a path in a pre-filled list, not that they read it. This is the same as SPEC-267 today.
- **R-2.** A change in `main` to context lines adjacent to the step's hunks voids the binding (AD-5). That is an over-refusal.
- **R-3.** The pre-PR verdict runs author-editable code (AF-5).
- **R-4.** `BF:` ids are agent-chosen (AD-8).
- **R-5.** One CODEOWNER only, until #1936. A decline by any verified CODEOWNER governs over an earlier authorize by another.

---

## 4. Slices (each ≤15 files including tests; each independently mergeable)

| # | Slice | Files (indicative) | Protected? | Depends on | Merge hangs on |
|---|---|---|---|---|---|
| **S1** | Verifier, inert: parse/render, pure `decide`, binding, bounded fetcher, CLI, audit (AD-2 to AD-5, AD-8 rule, AD-10). The `parse_codeowners_humans` extraction. The live edit-field probe record. | `scripts/framework/human_authorization.py` (new), `scripts/framework/requester_trust.py` (extraction only), `tests/framework/test_human_authorization_predicate.py` (new), `…_parse_render.py` (new), `…_binding.py` (new), `…_fetch.py` (new, fault injection), `…_cli.py` (new, exit contract, audit), `tests/framework/test_requester_trust*.py` (pin unchanged behaviour), `scripts/framework/framework_consumer_files.txt`, `research/findings/api-field-shape-verification.md`, `SCRIPTS-INDEX.md`: 11 | **Yes**: `scripts/framework/**` | — | human approval only (no caller). `security-reviewer`, `privacy-reviewer` |
| **S2** | Wire-in and normative contract, landed together so the behaviour and the contract never disagree. Evaluator conditions 7, 7b, 10 and 14, `:121`, `:219`, SPEC-82 list (AD-6, AD-7). `risk-assessor` `escalated: github-act`. Overseer re-verify. `pr_readiness` REQ-W-07. Contract §1, §6a, §7, §8 (version bump). | `.claude/agents/oversight-evaluator.md`, `.claude/agents/overseer.md`, `.claude/agents/risk-assessor.md` (all top-level session), `contract/OVERSIGHT-CONTRACT.md`, `contract/step-manifest.template.yaml` (`contract_version: "2"`), `scripts/automation/lib/pr_readiness.py`, `tests/automation/test_pr_readiness.py`, `tests/framework/test_human_authorization_wiring.py` (new: REQ-3 grep, REQ-11 hand-written-file test, legacy INFO), `tests/framework/test_human_authorization_e2e.py` (new: REQ-1 AC with a GitHub fake, CRITICAL and Condition-10), `DECISIONS.md`: 10 | **Yes**: `.claude/agents/**`, `contract/**`. **CODEOWNER review** | S1 | **ESC-1, ESC-4, ESC-5** (and ESC-3 confirms the binding the e2e test pins). `security-reviewer` |
| **S3** | Human-facing text (AD-9). Orchestrator block replaced by `render-request` output. Worker escalation text. Runbook heredoc removed. | `.claude/agents/oversight-orchestrator.md`, `.claude/agents/worker.md` (top-level session), `bootstrap/worker-cron-prompt.md` (if it names the act), `docs/OVERSIGHT-RUNBOOK.md`, `tests/framework/test_auth_escalation_text.py` (new: no clone path, URL and form present, no ADR-1928 AD-9 forbidden strings): 5 | **Yes**: `.claude/agents/**`, `bootstrap/**`. **CODEOWNER review** | S2 | #1928 S3 rebase order only |
| **S4′** | *Only if ESC-1 is (C):* CONDITIONAL_PROCEED plus review-body coverage for non-CRITICAL `C10:*`. | `merge_authority.py`, `human_authorization.py` (review source, GraphQL edit check), overseer prose, tests: ≤6 | Yes | S2, #1913 AD-6 | ESC-1(C), ESC-2 |

**Order.** S1 → S2 → S3. **Codable now:** S1 needs no ESC answer. Its actor rule is REQ-2, which is not open. **Design now, merge after:** S2 waits on ESC-1, ESC-4 and ESC-5. S3 waits on S2.

**Contract version.** §8 lists "changing the filesystem protocol locations" as breaking. Removing a required §1 artifact is that change, so S2 bumps `contract_version` to `"2"` and records the migration in `DECISIONS.md`. No script reads `contract_version` today (grep: no readers in `scripts/`, `bootstrap/` or `bin/`), so the bump is a declaration to consumers, not a runtime switch.

**Unblocking #1776, #1968 and #1988.** After S2 merges, each branch merges `main` and re-runs the evaluator, which posts the AD-9 block. The human posts one comment. The free-form rulings already given earn no retroactive credit (§3 of the requirements).

### Test obligations (all deterministic; `gh` is a recording fake; no network)

- **S1:**
  - REQ-2 table: a verified CODEOWNER is accepted. Refused: the human-proxy App, the worker App, an unlisted `[bot]` App, a `type: User` login in `BOT_ACCOUNTS`, a non-CODEOWNER human, and a body naming the CODEOWNER posted by a non-CODEOWNER.
  - A CODEOWNER present only in the working-tree file is refused.
  - REQ-4: an edited comment, a deleted comment, a comment on another issue, `wrong-step`, and `stale`.
  - REQ-8: authorize then decline is unmet. Decline then authorize is met. A malformed newest CODEOWNER comment gives `malformed-latest`. Tied `created_at` values are ordered by id.
  - REQ-6: an empty, absent or non-overlapping `reviewed_files:` is refused. A `./`-prefixed path matches. Prefix and basename matches do not. The SPEC-267 fixtures pass.
  - REQ-7: an act covering `C10:x` leaves `BF:y` unmet.
  - REQ-9: one fault-injection case per exit-3 cause, including the pagination cap.
  - Binding: stable under a hostile `.gitconfig`. A whitespace-only commit changes it. A clean merge from base keeps it.
  - Render/parse round-trip.
  - Audit: exactly one event per candidate with every field present. An acceptance audit failure gives exit 4.
  - Import graph: nothing from `scripts/automation/**` or `scripts/oversight/**`.
- **S2:**
  - e2e: a CRITICAL step and a Condition-10 step are each authorized by one comment alone, and the evaluator returns PROCEED for those items.
  - A hand-written, well-formed auth file with no act leaves conditions 7 and 10 unmet and emits the legacy INFO.
  - `_check_critical_human_authorization` delegates to the verifier (an AST test).
  - The overseer re-verify can only add HUMAN_REQUIRED.
  - The doc-validator passes.
- **S3:**
  - The rendered escalation contains the issue URL and the form.
  - No human-facing block names a clone path or asks the human to write a file.
  - The heredoc is gone.

---

## 5. Requirement amendments (for pm-agent to record; the requirements file is not edited here)

- **AM-1 (REQ-4, AF-7).** Replace "postdates the pipeline's current authorization request" with "names the current content binding (REQ-5)". Supersession orders acts by `created_at`, then by id.
- **AM-2 (REQ-3, AF-3).** The verifier must not import `scripts/automation/**` or `scripts/oversight/**`. GitHub reads use its own bounded fetcher. Audit goes through the `audit_log` CLI as a subprocess.
- **AM-3 (REQ-2, AF-2).** The CODEOWNERS set is read from the server's default branch, never from the working tree.
- **AM-4 (REQ-5, AF-6).** The binding is `git patch-id --verbatim` with pinned diff options.
- **AM-5 (REQ-6).** `reviewed_files:` overlap is required on every authorize act, not only for condition 10.
- **AM-6 (REQ-7).** Condition-10 items are per signal (`C10:<signal>`). `RA-FALLBACK` is added for the `:121` fallback.
- **AM-7 (REQ-10).** `source` is `issue-comment` only in v1. Review bodies are deferred to S4′.
- **AM-8 (REQ-11, AF-8).** The domain structural-auth files are retired along with the main file.

Endorsed as written: REQ-1 (under ESC-1(A)), REQ-2, REQ-8, REQ-9, REQ-12, REQ-13, and the §3 non-goals.

---

## 6. Product-boundary checkpoint, startup gap, affected sign-offs

- **User-visible, routed (not mine to sanction):**
  - **Where and how the human authorizes (ESC-1).** This is a human-gate placement decision.
  - **Per-signal and per-finding naming** in the comment.
  - **A fresh act after any non-trivial merge from main** (ESC-3).
  - **Retiring the file outright**, which removes the only path for a consumer that does not use GitHub issues (ESC-5). HOS already requires GitHub for every other gate, so I judge that this removes no supported configuration.
  - **The contract version bump.**
- **Data retention.** Two audit events carry public logins and URLs, and no comment bodies.
- **Operational load.** Two or three GitHub reads per verify call. No new service, no new credential, no new trust boundary.
- **Startup gap: yes.** The file gate was designed when a human sat in the clone. It was not re-examined when the autonomous worker and the human-proxy split made GitHub the human's only interface (CLAUDE.md "Human-proxy session identity"), and that should have been settled in that architecture review. **Recommendation to the worker:** open or annotate a `startup-artifact-gap` issue against #2101. I have not filed it, per this task's instructions.
- **Affected sign-offs.**
  - **SPEC-267's coverage design stands.** Its rule is ported verbatim. Its artifact is replaced, so the S2 `security-reviewer` re-checks the port against SPEC-267's fixtures.
  - **SPEC-82's artifact list sign-off must be re-reviewed in S2**, because two entries are removed.
  - **The `pr_readiness` REQ-W-07 sign-off is re-reviewed in S2.**
  - **No approved design or code is orphaned.** VF-4 shows the file gate has never been satisfied, so no step was ever authorized under the superseded rule.

---

## 7. Open human escalations

pm-agent's ESC-1 to ESC-5 stand. The architect's positions:

| ESC | Architect | Note | Gates |
|---|---|---|---|
| ESC-1 | **Concur (A).** The comment on the issue or PR is the only authorizing act in v1 (AD-1, AF-1). | **This decides where the hardest human gate sits, so it is your ruling.** (B) moves the CRITICAL gate post-PR and depends on #1913's unbuilt module. (C) is S4′, later. | S2 |
| ESC-2 | **Concur: no** (moot under (A)). | Applies only to S4′. | S4′ |
| ESC-3 | **Concur: keep across a pure merge from base**, using the whitespace-exact patch-id (AD-5). | The stricter `head:<sha>` alternative is a one-function change. | S2 |
| ESC-4 | **Concur: yes**, each finding named `BF:<id>`. | Residual R-4. Without this, #1776 stays blocked. | S2 |
| ESC-5 | **Disagree with (ii). Recommend (i): retire, with no derived record**, together with the domain structural-auth files (AD-7). | (ii) keeps an authority-shaped file at the historical path, the most likely regression site. (iii) is rejected. | S2 |

```yaml
adr: ADR-2101
issue: 2101
codable_now: [S1]
design_now_merge_after: {S2: [ESC-1, ESC-3, ESC-4, ESC-5], S3: [S2, "#1928 S3 rebase order"], S4prime: [ESC-1=C, ESC-2, "#1913 AD-6"]}
hard_constraints_not_waivable: [REQ-2, REQ-9, AD-3]
escalations:
  - {id: ESC-1, tier: hard-tradeoff, options: {A: comment, B: conditional-proceed-approval, C: both}, recommended: A, gates: [S2], note: human-gate placement}
  - {id: ESC-2, tier: hard-tradeoff, recommended: "no (moot under A)", gates: [S4prime]}
  - {id: ESC-3, tier: hard-tradeoff, options: {default: patch-id-verbatim, strict: head-sha}, recommended: default, gates: [S2]}
  - {id: ESC-4, tier: hard-tradeoff, recommended: yes-named-by-id, gates: [S2]}
  - {id: ESC-5, tier: hard-tradeoff, options: {i: retire, ii: derived-record, iii: handwritten-fallback}, recommended: i, gates: [S2], note: disagrees with pm default ii}
```

---

## 8. Notes and follow-ups (named, not filed here)

- **N-1 → pm-agent.** `_find_human_approval` (`merge_authority.py:44-64`) matches one configured login by equality and does not apply `is_bot_reviewer`. That is safe today because `HUMAN_REVIEWER` is a human. #1936 should route it through the AD-3 actor rule.
- **N-2 → pm-agent.** The legacy `.claudetmp/oversight/human-tier-override.md` (`oversight-evaluator.md:431-433`) has the VF-3 defect. It is outside §3's scope.
- **N-3.** If the human posts a ruling in free text, the AD-9 block is the remedy. A "did you mean `/hos authorize`?" hint from the verifier is optional and is not planned.

## Escalation flag (CORE self-flag)

RISK: HIGH. The verifier becomes the sole decision point for the CRITICAL and structural human gates, on protected surfaces. A defect in AD-3 or AD-4 is a bot-satisfiable gate.
CONFIDENCE: HIGH on AF-2, AF-3, AF-5 and AF-8 and on the reuse citations, all read in this session. MEDIUM on AD-4's REST `updated_at` behaviour for non-edit events, which S1 must probe live. MEDIUM on the patch-id over-refusal rate after merges from main (R-2).
BLAST RADIUS: every gated step's path to a PR (evaluator, `pr_readiness`), the overseer's merge decision on gated PRs (it can only add a gate), contract §1, §6a, §7 and §8 for every consumer, and two audit events. No label, selection or #757 path changes.
Change classification: STRUCTURAL. It replaces a required contract artifact, adds a verification obligation and a human-facing act, and bumps `contract_version`.

## Human Review Required

ESC-1 (where the hard human gate sits) and ESC-5 (where I disagree with the pm-agent default) must be answered from your own GitHub account before S2 merges. ESC-3 and ESC-4 confirm defaults that S2's tests pin. S1 may be built and reviewed now. REQ-2, REQ-9 and AD-3 are not open to any answer. For each slice, your own-account approval of the protected-surface PR is the final gate.
