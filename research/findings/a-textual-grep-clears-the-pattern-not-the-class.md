# Finding: A Textual Grep Clears the Pattern, Not the Class

**Role:** audit-scope — a defect class defined by *what a value's derivation does* (re-derive
instead of consult the source of truth) is not reducible to *how a broken instance was spelled*

**First observed:** 2026-08-15, audit #1407 (follow-on to #1386)

---

## The Finding

A bug fixed by correcting one string (`../..` → `..`) invites a follow-up grep for that same
string across the tree, and a clean grep reads as "the class is closed." It isn't, when the class
is semantic rather than syntactic: *a value with one authoritative source, independently
re-derived elsewhere*. That defect shows up in as many syntactic shapes as there are ways to
compute a path or an identity — directory arithmetic is only one of them.

#1386 was a directory-arithmetic instance: `validate_setup.sh` computed a project-config path as
`$REPO_ROOT/../..` instead of `$REPO_ROOT/..`. The one-line fix landed clean, and a full-tree grep
for the literal `../..` pattern turned up nothing else live. #1407 was filed anyway, specifically
because the grep result *proves the pattern is gone, not that the class is*.

It wasn't. The same class recurred in three unrelated syntactic shapes, none of which contain
`../..` and so none of which the clean grep could have found:

1. **Wrong assumed depth in `BASH_SOURCE`/`dirname` arithmetic**, spelled with an extra path
   segment rather than an extra `..`: `scripts/run_panel.sh:187,287` appends
   `/scripts/oversight/...` to a directory that is already `.../scripts`, producing a doubled,
   nonexistent `scripts/scripts/...` path — the exact same "wrong-depth self-location" defect as
   #1386, spelled with a segment name instead of a `..` (#1408).
2. **Fixed identity paired with self-derived location, never cross-checked**: `bin/hos-worker` /
   `bin/hos-overseer` hardcode their role by which file you run, then derive their target repo
   from their own `git rev-parse --show-toplevel` — never consulting the registry that
   `bin/hos-cron` treats as authoritative for the same question. No arithmetic is wrong here; the
   defect is structural — two independently-asserted facts (role, location) that are never
   required to agree (#1409).
3. **A hardcoded list re-deriving a canonical list**: `validate_setup.sh`'s `REQUIRED_AGENTS`
   array duplicates (a subset of) `scripts/framework/consumer_agents.txt` by hand, the same
   consolidation HOS already made once for two *other* consumers of that list (#225) but never
   extended to this third one. No path arithmetic at all — the re-derived value is a list, not a
   directory (#1410).

None of these three would be caught by re-running the grep that closed #1386. All three are the
same class the way #1386 is: a place that answers "where/what/who is X" by computing an answer
locally instead of asking the one place that already knows.

## Why this matters beyond this one audit

The instinct after a fix is proven correct — grep for the broken string, confirm it's gone,
call the class closed — is cheap and looks rigorous. It answers "did this exact typo recur?"
It does not answer "does this failure mode recur?" Those are different questions whenever the
defect is defined by a *relationship* (independent re-derivation vs. single source of truth)
rather than by a *string*. Closing the string search and treating it as closing the class is
itself a smaller instance of the same error this audit exists to catch: trusting a local,
easily-checked signal (the grep) as if it answered the actual authoritative question (is the
class present anywhere in the tree, in any of its possible shapes).

The corrective is not "grep harder" — it's asking, for each instance found, what makes it an
instance of the class (a value with one true source, computed independently elsewhere) rather
than what makes it look like the fixed bug syntactically. That question has to be asked freshly
per candidate site; it can't be automated into a single search pattern, because the class has no
single textual signature by construction — if it did, it would already have been caught the first
time.

## Related

- #1386 — the field report and its one-line fix (directory-arithmetic instance).
- #1407 — this audit; scoped explicitly around the semantic-vs-textual distinction.
- #1406 / #1398 — fix destination for the config-dir sub-instance of the class #1386 exposed.
- #1408 / #1409 / #1410 — the three additional instances this audit found, filed individually.
- [[refactor-to-reusable-is-a-quality-audit]] — adjacent finding on duplication as a quality
  signal, worth cross-referencing if it exists in this tree.
