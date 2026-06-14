# Finding: An oversight gate must declare its own dependencies and fail loud — a transitive dep is a silent time-bomb

**Role:** oversight-mechanism — the gate that enforces oversight cannot itself fail silently

**First observed:** 2026-06-13, CPS real-world test run (CPS#73/#74, HOS#48/#49)

---

## The finding

The sign-off gate (`signoff_gate.py`, `sign_off.sh`) parses the step manifest with PyYAML. PyYAML was **never declared** in `requirements.txt` — it happened to be present in the oversight venv only because `bandit`, `detect-secrets`, and `libcst` pull it transitively. The gate imports `yaml` *directly* but depended on luck for it to be there.

Two failure modes followed, and both are the worst kind for an oversight component — **silent**:

1. **Unpopulated / partial venv → `import yaml` fails → the gate crashes before doing any work.** In the CPS overnight run this produced **54 consecutive silent crashes** (9 roles × 6 branches): sign-off stamps were never written, and the *next* gate then reported every stamp as "stale." The oversight signal was absent, but nothing announced its absence — the pipeline read missing-stamp as a *different* condition (stale) and carried on.
2. **Re-exec loop with no guard.** The recovery path was `if venv_python.exists(): os.execv(venv_python, ...)`. If the venv exists but lacks PyYAML (a partial install), this re-execs the process *into itself* forever — a hang dressed as recovery.

## Why it matters for scalable oversight

A gate exists to convert "was this overseen?" into a hard pass/fail a human can trust. When the gate **fails silently**, it produces the most dangerous possible output: the *appearance* of a clean run with *no* underlying check. 54 missing sign-offs that read as "stale stamps" is indistinguishable, to a glancing operator, from a benign re-run prompt — the oversight simply evaporated and the dashboard stayed green-adjacent.

Three rules fall out, all instances of principles already in this corpus:

- **Declare what you import.** A load-bearing dependency that is satisfied only transitively is an undeclared invariant — exactly the class of "rule with no verification mechanism" (`unenforceable-rules-need-verification-mechanisms.md`) but at the package level. The day `bandit` drops PyYAML, the gate breaks and no test catches it. Pin it directly: `PyYAML>=6.0` in `requirements.txt`.
- **An oversight gate must fail loud, never silent (`jidoka-reactive-pipeline.md`).** Missing-because-crashed and stale-because-old must not collapse into one indistinguishable state. The fix surfaces an explicit, actionable error (`repair the venv: ./ensure_venv.sh`) and exits non-zero instead of leaving an absent stamp to be misread downstream.
- **A recovery path needs a termination guard.** `os.execv`-to-recover must check it is not already running as the target interpreter (`venv_python.samefile(sys.executable)`), or "self-heal" becomes "spin forever." Automation that retries must bound its retries — the ratchet (`ratchet-principle.md`) applied to process recovery.

## The mechanism (the fix)

- `requirements.txt`: add `PyYAML>=6.0` as a **direct** dependency with a comment explaining it must not rely on the transitive provider.
- `signoff_gate.py`: add a loop guard — re-exec into the venv Python only when not already running as it; otherwise emit a clear "PyYAML missing from the venv — repair it" error and exit 2.
- The deeper, still-open instance: other gates/validators resolve their tools (`detect-secrets`, `radon`) on the bare `PATH` rather than through the venv, so they report "not installed" even when the venv has them (HOS#102). Same root cause — the gate does not consistently run inside the environment that holds its tools.

## The trap it avoids

The seductive wrong fix is "the venv always has PyYAML, so just point at the venv" — which is what the *first* fix (HOS#48/#49) did, and it was insufficient because the premise ("always has") was an unverified transitive accident. Closing an issue on a fix whose correctness rests on a coincidence is how a gate ships looking fixed while remaining a time-bomb. The CPS real-world run is what re-surfaced it — a second, independent environment re-derived the failure the closed issue thought it had killed.

## Provenance

Observed 2026-06-13 during the CondoParkShare real-world HOS test (CPS#73/#74, filed against HOS#48/#49 which were already closed). The venv-detection fix shipped in `v0.1.0` but rested on PyYAML's transitive presence; the direct-declaration + loop-guard hardening followed. Related: `release-gate-catches-its-own-missing-oversight.md` (a fix that looked complete but wasn't, caught by re-validation in a fresh context), `jidoka-reactive-pipeline.md` (fail-loud / stop-the-line), `unenforceable-rules-need-verification-mechanisms.md` (undeclared invariant), `ratchet-principle.md` (bounded recovery).
