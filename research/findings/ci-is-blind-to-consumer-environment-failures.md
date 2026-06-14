# Finding: CI is structurally blind to consumer-environment failures — only a real-world install test surfaces them

**Role:** oversight-mechanism — the oversight tooling must run in the overseer's environment, and only a field test proves it does

**First observed:** 2026-06-13, CondoParkShare real-world HOS test run (HOS#73/#74, #101, #102, #103)

---

## The finding

A continuous-integration job runs in an idealized environment: a fresh Linux container where the workflow installs every tool globally before the gates run. That environment is *not* the one a human operator actually runs the oversight pipeline in. The first real install — CondoParkShare on a developer's macOS machine — surfaced a whole class of failures that every green CI run had been blind to:

- **bash-4 idioms on bash 3.2.** `mapfile` is a bash-4 builtin. macOS ships bash 3.2 (the last GPLv2 release). Three gates (`run_validators.sh`, `gates/type_check.sh`, `gates/portability_check.sh`) used `mapfile` and were therefore *inoperable* on the operator's machine — including, with some irony, `portability_check.sh` itself (#101). CI never caught it because CI runs bash 5.
- **Tools resolved off bare `PATH`, not the venv.** `secret_scan.sh` used `command -v detect-secrets`. The oversight venv has `detect-secrets`; the bare PATH does not. So on a real machine the gate silently downgraded to a weak grep fallback and reported "detect-secrets not installed" (#102). CI installs detect-secrets globally, so `command -v` always succeeded there.
- **Undeclared / transitive dependencies** (the sibling finding `oversight-gate-must-declare-its-deps-and-fail-loud.md`, HOS#73/#74): PyYAML present only transitively. CI installs it explicitly in the workflow, masking the missing declaration.
- **PEP-668 externally-managed environments** (#98) and **install-time placeholder substitution** (#99): both only bite on a real target, never in the framework's own CI.

Every one of these passed CI and failed in the field. The common shape: **CI's environment is a generous superset of the operator's** (newer shell, all tools global, deps pre-installed), so any bug that depends on the *absence* of something is invisible to it.

## Why it matters for scalable oversight

The oversight pipeline is the thing a human trusts to tell them whether AI-generated code is safe to ship. If that pipeline silently doesn't run — a gate crashes with `mapfile: command not found`, or downgrades to a grep stub and announces a pass — the human is overseeing *nothing*, while the dashboard stays green. The failure is not "the code was bad"; it is "**the overseer's instrument was broken and said it was fine.**" That is strictly worse than no gate, because it manufactures false assurance.

So a system whose product is *human oversight* has a non-negotiable requirement its CI cannot satisfy: **the gates must actually execute in the overseer's real environment.** Proving that requires running the full install + gate suite on a real, un-idealized operator machine — exactly what the CPS field test is. The field test is not a nice-to-have integration check; it is the *only* place a large, structurally-invisible class of oversight-instrument failures becomes observable.

## The mechanism

- **Portability floor for the gates themselves.** The gate scripts target the operator's likely shell (bash 3.2 on macOS): no `mapfile`, no bash-4-isms; `cut_release.sh` already carries the note "portable to bash 3.2." Resolve every tool through the oversight venv (`$VENV_BIN/<tool>`, `$OVERSIGHT_PYTHON`) rather than bare PATH; declare every imported dependency. The framework's *own* `portability_check.sh` gate should be pointed at its own scripts.
- **A real-world install test as a first-class oversight checkpoint.** Install from a published release onto a real machine and run the gates; treat each divergence from CI as a field report. The value is precisely the failures CI's idealized environment cannot reproduce.
- **Fail loud, not silent (`jidoka-reactive-pipeline.md`).** A tool that is missing in the operator's environment must announce it (`SKIP: detect-secrets not in oversight venv — run ensure_venv.sh`), never quietly substitute a weaker check and report a pass.

## The trap it avoids

"All gates green in CI" reads as "the oversight pipeline works." For a framework that ships to other machines, that inference is false: it means the pipeline works *in CI's environment*, which no operator has. The trap is shipping a framework whose oversight instruments are validated only against the one environment that can never expose their portability bugs — and discovering, only because a human happened to run it for real, that the instruments were inert.

## Provenance

Observed 2026-06-13 during the CondoParkShare real-world HOS test. `mapfile` portability (#101) fixed across `run_validators.sh`, `type_check.sh`, `portability_check.sh`; venv tool-resolution (#102) fixed in `secret_scan.sh`; undeclared PyYAML (#73/#74) in the sibling finding. Related: `oversight-gate-must-declare-its-deps-and-fail-loud.md`, `release-gate-catches-its-own-missing-oversight.md` (re-validate the shipped artifact in a fresh context), `jidoka-reactive-pipeline.md` (fail-loud), `tooling-drift-in-validation-pipelines.md` (a gate that isn't actually running is the limiting case of tooling drift).
