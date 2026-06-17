# Finding: API Field Shapes Must Be Verified Against Live Responses — Documentation Assumptions Cause Silent Correctness Failures

**Role:** oversight-mechanism — correctness of machine-readable protocol parsing

**First observed:** 2026-06-16, `merge_authority.py` R5.6.2 implementation, issue #348

---

## The Finding

The release authorization protocol (worker.md R5.6.2) was implemented to check that the GitHub-API-verified actor who performed the re-assignment was a human CODEOWNER. The implementation read `actor.login` from the `assigned` event in `GET /repos/{o}/{r}/issues/{n}/events`.

During the first live run, `actor.login` returned `HOSWorkerTutelare` — the bot account, not the human who performed the assignment. The authorization check failed because the bot appeared to be self-assigning.

The actual GitHub Issues Events API structure:
- `actor`: the **assignee** (who was assigned TO)
- `assigner`: the **performer** (who did the assigning)

The field `assigner` is undocumented in some GitHub API references, or documented inconsistently. The implementation assumed `actor` = performer based on the common REST convention that `actor` means "who performed the action." For assignment events, GitHub uses `actor` differently.

**The broader pattern:** REST API field naming is not standardized across event types. An `actor` in a `labeled` event means the labeler (the performer). An `actor` in an `assigned` event means the assignee (the affected party). The same field name carries different semantics depending on the event type.

## Why It Matters for Automated Pipelines

A human reading the GitHub web UI sees the assignment correctly attributed. An automated pipeline reading `actor.login` will silently misread every assignment event, treating the assignee as the performer. The authorization check inverts: the bot (being assigned to) fails the "must be human CODEOWNER" check because it IS the bot — even though a human performed the assignment.

This failure mode is particularly dangerous because:
1. It passes in testing (the code runs without error)
2. It fails silently in production (the authorization check rejects valid authorizations)
3. The failure looks like a configuration problem or a permissions issue, not a field-name bug

## The Fix and the Verification Obligation

Fix: use `assigner.login` (the performer) not `actor.login` (the assignee) for assignment events.

The verification obligation in the technical design (SPEC-evaluator-re-derivation.md §6.4): *"Before relying on field paths, the coder must confirm against a live API response that the payload exposes the expected fields."* This is a standing obligation for any code that parses GitHub API event payloads — verify the field shape against a real response before writing the code that depends on it.

## Evidence

- Issue #348: `actor.login` vs `assigner.login` in R5.6.2 — discovered during the first live run of the release authorization protocol
- `merge_authority.py` R5 §6 condition 2: corrected to use `assigner.login`
- GitHub Issues Events API: the `assigned` event carries both `actor` (assignee) and `assigner` (performer); the `labeled` event carries only `actor` (labeler/performer); the semantics differ by event type

## Implications for Research

1. **Field name conventions are not a substitute for empirical verification.** `actor` conventionally means "who did the action" in most REST APIs. GitHub is an exception for certain event types. Conventions reduce the effort of reading documentation; they do not replace reading documentation.

2. **Silent correctness failures from API shape assumptions are worse than loud errors.** A misread that causes a crash is immediately visible. A misread that causes an authorization check to silently reject valid authorizations may go unnoticed for many cycles.

3. **Protocol implementations should include a live-response verification step in the testing suite.** A unit test that mocks the API cannot catch a wrong field name — it will mock the wrong field faithfully. An integration test against the live API (or a recorded fixture) would catch this class of bug.

4. **Event-type-specific field semantics should be explicitly documented in any spec that parses event payloads.** The SPEC-evaluator-re-derivation.md §6.4 "coder verification note" is the right pattern: name the expected fields, require verification, and provide a route-back path if the shape differs.

## Related findings

- `reviewer-agents-file-confident-non-reproducing-reports.md` — a different class of silent failure (reports that don't reproduce); the common thread is that confident-looking output can be wrong without any error signal
- `working-state-invariant.md` — implementation assumptions about external state that don't hold; this is the API-field-specific instance
