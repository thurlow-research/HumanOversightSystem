# Finding: An anti-gaming re-derivation exempted the one role it most needed to police

**Role:** oversight-mechanism — the distrust check that re-derives self-classifications had a hole exactly at its most important input

**First observed:** 2026-06-13, v0.1.1 release-gate self-review

---

## The finding

The evaluator's anti-gaming control (#74) defends against a reviewer mislabeling a touched domain as `N/A` to skip its own review: it independently re-derives, from the diff, which domains were actually touched, and fails closed if an `N/A`'d role's domain *was* changed. The whole point is to not trust the self-report.

But it carried an explicit carve-out: *"`code-review` is never N/A'd by the orchestrator, so it is not in scope here."* The premise is false. `code-reviewer` can **self-write** `Status: N/A` ("no application code in diff", per `post-change-sweep`). So `code-review` N/A *does* occur — and when it does, it is the **one role whose waiver the distrust check never re-derives**. A self-`N/A`'d (or forged) code-review on a diff that genuinely contains application code sails through the exact check the mechanism exists to provide — and `code-review` is the *foundational* review, the one most worth gaming.

So the anti-gaming control had a hole precisely at its highest-value target, justified by a rationale ("the orchestrator doesn't N/A it") that was irrelevant to the actual threat ("the *reviewer* N/A's itself").

## Why it matters for scalable oversight

A distrust mechanism is only as good as its coverage, and coverage gaps cluster exactly where an attacker (or a lazy/looping agent) would aim: the most important, most load-bearing check. Exempting `code-review` from re-derivation is the security-equivalent of skipping authentication on the admin endpoint because "admins don't usually log in that way." The exemption's stated reason described one *path* by which the value gets set (the orchestrator) and ignored the *other* path (self-write) — and the threat lives entirely on the ignored path.

The rule: **a re-derivation/distrust check must cover every role that can produce the self-report it distrusts — especially the most important one — and its scope must be justified by the threat model, not by the common case.** "This role is usually set by a trusted actor" is not a reason to exempt it if an untrusted actor *can also* set it.

## The mechanism (the fix)

Bring `code-review` into the #74 re-derivation scope: re-derive any `Status: N/A` for `code-review` against the diff exactly as for every other role — if the application-code domain (`**/*.py`, etc.) was touched, COMPLIANCE FAIL. Delete the carve-out; the rationale was about *who usually sets the value*, which is orthogonal to *who can forge it*.

## How it was found

The framework's own release-gate **self-review found this in its own evaluator**, adversarially — an instance of the system applying its distrust discipline to itself (`self-governance-recursion.md`). It is also a data point for the convergence finding: an adversarial reviewer on a rich governance corpus keeps surfacing *real* holes (this one had shipped, undetected, through prior releases), which is why the honest convergence bar is "zero-NEW-all-tracked," not "zero."

## Provenance

Observed 2026-06-13 during v0.1.1 self-review convergence. Fixed in `oversight-evaluator.md` (#74 scope now includes `code-review`). Related: `self-classification-cannot-gate-the-human-boundary.md` (re-derive, don't trust), `the-recorder-must-not-be-in-the-recorded-set.md` and `a-gate-must-not-confuse-unreadable-with-unsafe.md` (sibling self-review/gate-integrity findings), `nondeterministic-review-gate-converges-on-zero-new.md` (why the gate kept finding real things).
