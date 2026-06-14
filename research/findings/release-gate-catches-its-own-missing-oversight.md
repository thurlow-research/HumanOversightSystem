# The release gate caught the framework's own missing oversight — and why you ship a re-validated tag, not the trunk

## The finding

A system that scales human oversight must answer "what, exactly, are we shipping, and was *it* overseen?" The naive answer — "whatever is on the main branch right now" — fails in a specific, repeatable way once development is batched: **commits land on a branch after its PR is merged, and silently never reach main.** The merged artifact is missing fixes everyone believed were in it. We hit this **three times in one session** (install fixes, then governance fixes), and the second time the *missing* fixes were the anti-gaming, fail-closed oversight controls themselves.

The defect was invisible to inspection — `main` looked complete; the PRs were green and merged. It was surfaced by **re-running the validation gate at release-cut time**: the gate's self-review re-found a contradiction (an agent documented as a fixer but lacking the write tool) that had been fixed weeks of commits ago — because that fix was stranded on a closed branch. The gate **refused to cut the release** on a trunk that was missing its own oversight hardening.

## Why it matters for scalable oversight

Two distinct oversight lessons, both about the gap between "we reviewed it" and "we shipped what we reviewed":

1. **Validation at merge-time is necessary but not sufficient.** Each PR was validated and approved. Yet the shipped trunk was defective, because the trunk is an *integration point* where things can be lost between approval and inclusion. Oversight that stops at the PR boundary trusts the merge mechanics to faithfully carry approved work onto the trunk — and that trust is misplaced under batching.

2. **The unit of "what was overseen" must be a pinned, re-validated artifact, not a moving branch.** The fix is to cut a release from a **tag that the full gate re-validates at cut time**, and have consumers deploy *that* — never `main`-HEAD. The re-validation is the second, independent check that the artifact about to ship actually contains the controls it claims. Here it earned its existence on the very first release: it caught that the trunk had lost the human-gate-bypass and fail-open fixes, before any consumer installed them.

This is the same principle as the rest of the system — **don't trust a self-reported state; re-derive it from the artifact** — applied at the release boundary. "main passed CI when each PR merged" is a self-report by the merge process; re-validating the tag is the independent re-derivation.

## The mechanism

- **Release = a tag whose contents the full validation suite re-runs against and passes** (static → self-review → cross-vendor → docs → compliance). A failing re-validation blocks the tag. Consumers install from the published release, which records its version in the target (`.hos-release`), so every deployment is attributable to a defined, re-validated state.
- **Recovery when stranding is detected:** the gate's finding is the signal; recover the stranded commits onto the trunk (cherry-pick), re-validate, then cut.
- **Process backstop:** the stranding root cause is "push after merge." A merger-equals-pusher discipline (the same actor that pushes a branch also merges it, and only when complete) removes the race; a CI check that flags a branch with commits added after its merge would catch the rest.

## The broader pattern

This is oversight applied recursively to the oversight system's own delivery. The framework's thesis — *re-derive anything that gates a human decision rather than trusting a self-report* — extends to its own releases: the trunk's completeness is a self-report by the merge process, and the release gate is the independent re-derivation that caught the report was wrong. A system that gates *code* but trusts its *own deployment* has an unguarded boundary exactly where it matters most: the artifact people actually run.

## Provenance

Observed 2026-06-13 cutting the first `v0.1.0` release. Three stranded-commit incidents in one session; the release gate's self-review caught the second (governance hardening missing from main) by re-finding an already-fixed contradiction. Recovered via cherry-pick + re-validate. See `DECISIONS.md` D36 (release-pinned install), the merge-protocol change (merger==pusher), and `ratchet-principle.md` / `self-classification-cannot-gate-the-human-boundary.md` for the same re-derive-don't-trust principle one layer down.
