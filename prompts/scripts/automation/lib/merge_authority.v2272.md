# Prompt artifact — #2272 (record_pr_bounce cap defaults to BOUNCE_CAP)

- **Issue:** #2272 (residual 4 of #2263, carried forward after PR #2271)
- **Source files:** `scripts/automation/lib/merge_authority.py`, `tests/automation/test_bounce_lock.py` (and any existing test that relied on the `None` default); `.claude/agents/overseer.md` §4a/§4c (authored by the top-level worker session, not `coder` — agent definition file)
- **Design:** the issue's "Required" list; #2227's lock design (`prompts/scripts/automation/lib/merge_authority.v2227.md`) stays the contract for everything else
- **Model:** claude-opus-5-5[1m] (worker, autonomous cycle worker-hos-261107200501-4171299)
- **Date:** 2026-11-07
- **Risk tier:** HIGH (security surface `scripts/automation/lib/**`; protected surface `.claude/agents/**`)
- **Human review status:** none yet; CODEOWNER review applies at merge.

## Prompt (as dispatched to `coder`)

Fix issue #2272 in `scripts/automation/lib/merge_authority.py`. Today `record_pr_bounce(..., cap: Optional[int] = None)` enforces the bounce cap under the per-(repo, cid) flock only when the caller passes `cap=`. A caller that omits it (for example the overseer following `overseer.md` §4c's narrated direct call) gets no lock-time cap check, so two concurrent bounces can exceed `BOUNCE_CAP`.

Required (stop and report if any part is impossible as stated):

1. **Default to the cap, opt out explicitly.** Omitting `cap` must enforce `BOUNCE_CAP`. Resolve the default **at call time** (a module-private sentinel default, resolved to the current `BOUNCE_CAP` inside the function), not at definition time — tests monkeypatch `merge_authority.BOUNCE_CAP` (see `tests/automation/test_merge_authority_cli.py` ~1925) and the default must follow it. A caller that genuinely needs no cap must say so explicitly: accept `cap=None` as the explicit opt-out and document it in the docstring as such. Keep `cap` keyword-only. Validate the value: a non-int / bool / negative cap raises `ValueError` before any GitHub call or lock.
2. **Callers.** `merge_authority_cli.py::_write_bounce` already passes `cap=merge_authority.BOUNCE_CAP`; leave it. `git grep -n "record_pr_bounce("` must show no production caller relying on an uncapped default. Do not change the CLI's behaviour or JSON payloads.
3. **Docstring.** Update the `record_pr_bounce` docstring paragraph about the lock/cap to say the cap is enforced by default and `cap=None` is the explicit, documented opt-out.
4. **Tests** (hermetic, no network, temp only via pytest `tmp_path`; the suite enforces zero leaked temp entries; follow the existing patterns in `tests/automation/test_bounce_lock.py`):
   - Two concurrent direct `record_pr_bounce` calls **without `cap=`**, with different new findings, at `bounce_count == BOUNCE_CAP - 1`, produce exactly one comment post and one `pr-bounced` event; the other returns `skipped=True, at_cap=True`.
   - A direct call without `cap=` at `bounce_count == BOUNCE_CAP` posts nothing, writes nothing, returns `at_cap=True`.
   - The default follows a monkeypatched `BOUNCE_CAP`.
   - `cap=None` explicitly still posts past the cap (opt-out preserved).
   - Invalid `cap` values raise `ValueError` with no GitHub call.
   - Fix any existing test that bounced past the cap while relying on the `None` default: pass `cap=None` explicitly only where the test's purpose is not about the cap, otherwise adjust the expectation. Do not weaken any assertion.
5. Run `scripts/oversight/.venv/bin/python -m pytest tests/automation/test_bounce_lock.py tests/automation/test_bounce_gate.py tests/automation/test_merge_authority_cli.py tests/automation/test_route_pr.py -q` and black/isort on the changed files (format **before** reporting, so no formatter commit lands after review).

Do not edit `.claude/agents/*` (the worker session does that). Do not run `git stash`, `git checkout`, or `git commit`; leave changes in the working tree. Report the diff summary and test results.

## Outcome (architect ruling, round 1)

- This replaces the `cap: Optional[int] = None` default recorded in `merge_authority.v2227.md` (item 2). That file is a historical prompt record and is left unedited.
- The worker first routed `overseer.md` §4a/§4c through `bash bootstrap/merge_authority.sh bounce`. The architect ruled that this pulls ADR-2209 S2 forward. TD-2209 says "Nothing calls `route` or `bounce` until S2", and the CLI's bounce comment tells the worker to post `/hos dispute <finding-id>`, which nothing handles before S1b/S3. Option A was taken. §4a/§4c keep the direct `record_pr_bounce(...)` call, which is now capped by default, and gain one line: never pass `cap=None`, and an `at_cap=True` result is handled as the `>= 2` branch.
- Deferred to ADR-2209 S2 (#2209): issue #2272's acceptance item "`overseer.md` §4c names the CLI".
- TD-2209 §3.6's `record_pr_bounce` signature now lists `cap` and `BounceResult.at_cap` (architect SHOULD_FIX-1).
