# Handling findings — signal vs. gate, and the false-positive triage discipline

If you find yourself **refactoring working application code to silence a scanner**, stop — you are chasing your tail. This doc is the antidote. Read it once; it changes how you read every HOS finding.

---

## 1. Two kinds of output — know which you're looking at

HOS produces two categorically different things. Treat them differently.

| | **Gates** (blocking) | **Validators** (signal) |
|---|---|---|
| Examples | lint, type-check, secret scan, security-HIGH (bandit), license/ScanCode | RN (risk number), cyclomatic/cognitive complexity, N+1 heuristic, hallucination-surface, prompt-audit, migration-risk |
| Behavior | **block** the build until resolved | **score** the code and feed the risk-assessor's inspection brief |
| Expected false-positive rate | **near zero** — tuned to be trustworthy | **deliberately non-zero** — they over-flag on purpose |
| When one fires | treat as real until proven otherwise | a **pointer for attention**, not a verdict |

If a **gate** fires (a secret, a GPL license, a security-HIGH), assume it's real. If a **validator** flags something, it is doing its job by drawing your eye — it has *not* condemned the code.

## 2. Why validators over-flag on purpose

The validators are sensitive by design: **a missed real risk is worse than a noisy flag.** They fail *toward* attention. A function that scores HIGH complexity isn't "wrong" — it's "look here first." The risk-assessor *expects* a pile of signals and ranks them; reviewers expect to dismiss some. High flag volume is not a defect, it's the operating point.

Convergence to a clean state does **not** come from a perfect first-pass scanner. It comes from **triage + upstream tuning** (see the convergence architecture in `METHODOLOGY.md`). That is the loop. Your job is to triage well and feed the tuning loop — not to make every validator go quiet by editing your app.

## 3. The triage discipline — three outcomes, never "chase"

For each validator finding, route it to exactly one of three outcomes:

1. **Real risk → fix it.** The flag found something. Good. Fix the code.
2. **True false positive → accept with a one-line rationale, move on.** Record *why* it's not a risk (in the step's sign-off notes / register entry), and leave the working code alone. **Do not refactor app code to satisfy a heuristic.** A one-line "accepted: N+1 heuristic mis-flags this `.select_related()` chain — verified single query" is the correct, complete response.
3. **Recurring FP *pattern* → file it upstream.** If the scanner mis-classifies a whole *category* (every `prefetch_related` reads as an N+1; every typed-dict access reads as a hallucination), the bug is in the scanner, not your code. File an issue on **HumanOversightSystem** labeled **`scanner-fp`** with the pattern and a minimal example. HOS tunes the scanner and ships it in the next release; you `--force` update. **The fix belongs in HOS, not in your app.**

The failure mode to avoid: silently contorting application code, run after run, to make a noisy heuristic happy. That degrades your code *and* hides the scanner bug from the people who can fix it.

## 4. Framework self-tests are not your pipeline

`validate_self.sh`, `validate_agents.sh`, `validate_scripts.sh`, `run_framework_validation.sh` validate **HOS itself** — they exist for people *developing the framework*. They are **not** part of your project's pipeline and you should not be running them against your app. If a guidance file in your repo tells you to, it's stale — delete that instruction.

**Your** pipeline is: the **gates**, the **validators** (`run_validators.sh`), the **risk-assessor**, and your **review agents**. That's it.

## 5. The feedback loop (how the scanners get better)

```
your app build → validator over-flags a category → you file scanner-fp on HOS
   → HOS triages + tunes the heuristic + ships a release
   → you hos_install.sh --force to the new tag → fewer false positives next build
```

This loop is the *intended* mechanism for scanner quality. A high false-positive rate today is the input to it, not a reason to abandon the validators or to bend your app around them. **File the `scanner-fp` issues** — they are how the noise goes down for everyone.

---

### Quick reference

- Gate fired? → real until proven otherwise.
- Validator flagged, and it's a real risk? → fix the code.
- Validator flagged, and it's genuinely fine? → accept + one-line rationale, leave the code alone.
- Same false positive across a whole category? → `scanner-fp` issue on HOS, don't patch your app.
- Tempted to refactor working code to quiet a heuristic? → don't. That's the tail-chase this doc exists to stop.
