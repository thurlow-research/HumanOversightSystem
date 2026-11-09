# Finding: An Outside Contribution Implements the Issue's Examples, Not Its Class

**Role:** oversight-mechanism. A public issue tracker works as a specification that outside contributors, increasingly automated ones, implement literally. When the acceptance criteria list examples, a contributor can satisfy every listed example and still break the class those examples stand for. Its own tests pass, because they were written from the same list. Independent review that checks the class, not the examples, is what catches it.

**First observed:** 2026-11-09 (issue #2301, PR #2303, closed unmerged).

---

## The Finding

1. **The issue.** The change classifier gives a CRITICAL tier floor to any path segment that *starts with* a payment word (`checkout`, `billing`, …). A new git-tooling script, `bootstrap/checkout_pr_head.sh`, was floored to CRITICAL because of its name, which stopped #2287 before its PR. The human-proxy filed #2301 to narrow the rule. Its acceptance criteria listed examples:
   - `bootstrap/checkout_pr_head.sh` must get no floor;
   - `app/checkout/views.py`, `checkout.py` and `src/checkout_service.ts` must stay CRITICAL.
2. **The contribution.** Seven minutes after the issue was filed, an account outside the organisation opened PR #2303 from a fork. Its write-up was clear, and its table-driven tests reproduced the issue's two example lists exactly, with all 152 classifier tests reported passing. The new pattern required `checkout` to be followed by `/`, `.`, end of string, or a `-`/`_` suffix that is not in a list of git words.
3. **The class it broke.** The issue's intent was "keep genuine payment checkout code at CRITICAL". Executed against realistic names (by the human-proxy, and independently by the overseer), the pattern **dropped the CRITICAL floor** from:
   - CamelCase names: `CheckoutPage.tsx`, `CheckoutController.java`, `checkoutApi.ts`;
   - plurals: `app/checkouts/views.py`;
   - names that happen to contain an excluded word: `checkout_ref_number.py`, `checkout-head.html`.

   Every listed example still behaved as specified. The defect lived entirely in the cases the list did not name. For a gate that scores risk, these are false negatives: payment changes that would skip the CRITICAL human gate.
4. **What caught it.**
   - The overseer returned `HUMAN_REQUIRED`, DO NOT MERGE. It tested the pattern string in isolation and named the same lost paths, without running the fork's code.
   - GitHub held all five fork workflow runs for maintainer approval, so none of the contributor's code ran in CI.
   - The human closed the PR with an explanation, from their own account.

## Why it matters

- **An acceptance list is a spec, and it will be met to the letter.** An internal worker reads the issue alongside the codebase's conventions and history. An outside contributor reading only the issue text implements what the issue *says*. Example-based acceptance criteria then become the whole definition of done. This echoes `a-textual-grep-clears-the-pattern-not-the-class.md`: clearing the named instances is not clearing the class.
- **Tests written from the same list cannot find the gap.** The contribution's tests were the issue's examples. Passing them shows the examples hold, not that the property holds. This is self-validation through a shared source, the test-side twin of `self-classification-cannot-gate-the-human-boundary.md`.
- **The weakness was structural, not only in the pattern.** The fix added a list of exempted words, which makes a file's *name* matter more to its risk tier. The same session had just ruled the opposite direction: the tier should come from what code does and from its history, not its name (#2302). That ruling was itself prompted when renaming the #2287 script was what resolved its tier. A name-based floor is author-controlled input, and a contribution that tunes the name logic tunes an author-controlled input.
- **Speed is a signal.** A PR within minutes of an issue being filed, on a public repository, suggests an automated contributor that watches issues. Throughput like that turns every issue into an invitation, and every under-specified issue into a likely miss.

## Implications for research

1. **Write acceptance criteria as the property plus counter-examples,** not as a list of examples. "Genuine payment checkout code stays CRITICAL, *including* CamelCase, plurals and arbitrary suffixes" would have rejected this pattern. Negative examples that sit outside the obvious list are the cheap defence.
2. **Independent review must test the class.** The overseer caught the defect by generating its own realistic inputs, not by re-running the contributor's tests. Supplying the reviewer with inputs the author did not choose is the same mechanism as `real-data-not-reviewer-diversity-caught-the-bug.md`.
3. **Holding fork CI is an oversight layer, not just a security setting.** It kept unreviewed outside code from running, and it left the merits decision to review, not to a green check the contributor's own tests produced.
4. **The channel was right; the review layers are what make it safe.** The human's policy (2026-11-09):
   - outside **bug-fix PRs are welcome**;
   - **features start as an issue**, and a PR follows once the maintainers bless it.

   #2303 was bug-fix level, so it used the right channel and simply carried a wrong fix. An outside PR skips the worker's inner loop and arrives at the overseer as a finished diff. What made it safe to accept the PR at all was the remaining layers: overseer review that tests the class, held fork CI, and the human's approval. The lesson is about the issue (write the property plus counter-examples, so any implementer, inside or outside, is held to the class), not about refusing outside work.

## What changed

- **PR #2303:** closed unmerged by the human, with an explanation of the lost cases and of #2302's direction.
- **Contribution policy:** bug-fix PRs are welcome, and features go to an issue first, with a PR after maintainer blessing. It is being written down as a contributing guide.
- **#2301:** annotated. Whoever builds it keeps the CamelCase, plural and suffix cases at CRITICAL with tests, checks the other payment words, avoids exemption lists, and checks #2302 first (it may supersede #2301).
- **#2302 (v0.7.10):** the tier comes from what code does and its history. A name may raise the tier, never lower it, and a rename never lowers it.

## Related findings

- `a-textual-grep-clears-the-pattern-not-the-class.md`: the same pattern, with named instances cleared and the class left open
- `real-data-not-reviewer-diversity-caught-the-bug.md`: inputs the author did not choose decide whether review catches the defect
- `self-classification-cannot-gate-the-human-boundary.md`: validation drawn from the same source as the thing validated
- `gate-on-computed-signal-not-self-reported-verdict.md`: the contributor's "152 tests pass" is a self-reported verdict
- `cross-vendor-review-finds-real-bugs.md`: independent review as the layer that caught it
