# Finding: A Decision Records Intent, Not Enforcement

**Role:** oversight-mechanism — a decision written into `DECISIONS.md` binds the code that existed when it was written, and nothing after

**First observed:** 2026-08-04, session `2026-08-04-controls-that-never-fire.md`

---

## The Finding

A design decision, correctly reasoned and durably recorded, does not propagate to code written
afterwards. It is a statement of intent at a point in time. Unless something *checks* it, each
new file is free to violate it, and the violation looks like ordinary code to every reviewer —
because the decision lives in a different document than the code it governs.

The failure is quiet in a specific way: nobody disagrees with the decision, nobody argues
against it, and nobody applies it.

## The concrete instance

`DECISIONS.md:305` records:

> **Resolve tools through the oversight venv, never bare `PATH`.** Use `$VENV_BIN/<tool>` and
> `$OVERSIGHT_PYTHON` (source `ensure_venv.sh`). `command -v <tool>` finds CI's global install
> but not the operator's venv, **silently downgrading the gate** (e.g. `secret_scan.sh` fell
> back to a weak grep and reported a pass).

The decision is right. It names its own prior incident. It specifies the mechanism.

The mechanism was applied at the orchestration layer — `run_validators.sh:27-29` sources
`ensure_venv.sh` and uses `$OVERSIGHT_PYTHON`. It was never applied to the validators' own
subprocess calls:

| File | Invocation |
|---|---|
| `static_analysis.py:49` | `["bandit", "-f", "json", "-ll", "-ii"]` |
| `static_analysis_js.py:68` | `["semgrep", "--config", …]` |
| `complexity_metrics.py` | radon, same pattern |

All three tools were **declared** in `scripts/oversight/requirements.txt` and **installed** in
`scripts/oversight/.venv/bin/`. All three were unreachable. The consequence was the one the
decision predicted, on a different gate: `static_analysis` (weight **0.15** — the security
dimension) and `complexity` (0.08) were dropped from every risk score computed on the machine,
because `composite_score()` ignores errored validators rather than zeroing them.

**Second occurrence of a failure the decision was written to prevent, roughly two months later.**

## Why it is distinct from an unenforceable rule

`unenforceable-rules-need-verification-mechanisms.md` concerns a rule an agent *cannot verify* —
it lacks the information to comply. This is the opposite: compliance was trivially available.
`ensure_venv.sh` existed, was already sourced one layer up, and the correct idiom was written
down with a worked example.

The gap is not capability, and not disagreement. It is that **a decision has no attachment
point in the code it governs.** A reviewer reading `static_analysis.py` sees a subprocess call
to a declared dependency. Nothing in the file, the diff, or the test suite refers to
`DECISIONS.md:305`. The decision and its violation never appear in the same field of view.

## Implications

- **A decision that constrains how code is written needs a mechanical check, or it applies only
  to the code present when it was made.** The check is usually cheap — here, a lint rule
  forbidding bare-name subprocess invocation of any tool in `requirements.txt` would have caught
  all three.
- **Recording the prior incident does not help.** `DECISIONS.md:305` names `secret_scan.sh`
  explicitly, and the same class recurred anyway. Prose memory does not transfer across authors
  or across months.
- **Prefer decisions that are structurally hard to violate** over decisions that are merely
  documented. A shared `resolve_tool()` helper that is the only way to reach a subprocess makes
  the decision unstatable in the wrong form.
- **When a decision is applied at one layer, check whether it was applied at every layer.** The
  orchestrator was compliant, which is what made the validators' non-compliance invisible — the
  system looked like it honoured the rule.

## Related

- `unenforceable-rules-need-verification-mechanisms.md` — the adjacent case: rules that cannot be verified
- `state-assertions-decay-faster-than-their-documents.md` — the same document/reality drift, applied to state
- **#1266** — the issue where this was found
- **DECISIONS.md:305** — the decision in question
