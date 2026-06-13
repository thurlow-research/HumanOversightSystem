# Self-classification cannot gate the human-approval boundary

## The finding

In a pipeline that scales human oversight by letting agents act autonomously on low-stakes changes and escalating only high-stakes ones, **the classification that decides "does a human see this?" cannot be performed solely by the actor whose work is being classified.** When the authoring agent both makes the change and labels its risk, the label is not an oversight control — it is the governed party self-reporting. Tightening the *definition* of the label (what counts as `structural` vs `additive`) does not fix this; it improves an honest classifier's accuracy but does nothing against a mistaken or motivated one. The control only becomes real when the label is **independently re-derived** from an artifact the agent cannot rewrite — here, the diff itself.

## Why it matters for scalable oversight

The entire efficiency claim of the system is that humans review a *fraction* of changes — the ones that cross a risk threshold — and trust automation for the rest. That claim rests entirely on the threshold-crossing decision being trustworthy. If an agent can place a change below the threshold by labeling it (whether through error, ambiguity, or optimization pressure toward "done"), the human-review fraction is no longer the high-risk fraction — it is the *honestly-labeled-high-risk* fraction, and the gap between those two is exactly the set of escapes the human never sees. The boundary that makes oversight scalable is only as strong as the weakest classifier sitting on it.

## The structural fix

Re-derive the loosening determination independently and deterministically:

- A small deterministic classifier (`scripts/oversight/change_classifier.py`) scans the diff for **mechanical structural-override signatures** (new dependency, new permission/auth state, new user-facing surface or route, new state enum). Any match forces `structural` regardless of the agent's label.
- The evaluator runs this as a compliance check; an uncovered structural change fails and escalates to the human before the PR opens.

Three properties make this work as an *oversight* control rather than just another check:

1. **It runs only in the loosening direction.** Re-derivation costs are paid only when the upstream determination would *reduce* scrutiny (an `additive` self-label, an N/A waiver). When upstream asks for more review, there is nothing to guard against. This is the ratchet (`ratchet-principle.md`) applied to the verification itself — a necessary property, because a check that fires on every change is too expensive to keep and gets disabled.
2. **It is biased to over-detect.** A false positive sends a benign change to a human (the safe direction); a false negative is the only real failure. The asymmetry of the boundary dictates the asymmetry of the detector.
3. **Escapes are recorded, not just blocked.** Every detected override is logged (`structural-override`), *including* when another gate happened to catch it. The covered-vs-uncovered ratio is an empirical **misclassification rate** — a direct measurement of how often the self-classification boundary would have failed without the independent check. That number is the research output: it quantifies the size of the gap this control closes.

## Generalization

The pattern recurs anywhere a governed actor self-reports the value that decides its own oversight level: risk-tier self-declaration (already guarded — risk-assessor can only raise a coder's tier, never lower it), N/A reviewer waivers (`#74`), and change-type classification (`#75`). The common rule: **a self-reported value may be trusted to escalate, never to de-escalate.** De-escalation must be independently re-derived or human-authorized. A system that violates this rule has an oversight boundary that any sufficiently-confident classifier can walk through.

## Provenance

Surfaced repeatedly by the Opus self-validator and the session critical review; implemented as contract §2a + `change_classifier.py` + evaluator conditions 9–10. See `DECISIONS.md` D33, issues #74 and #75. Related: `ratchet-principle.md`, `self-governance-recursion.md`.
