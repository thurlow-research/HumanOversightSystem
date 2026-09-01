# Finding: A Confidently Wrong Error Message Costs More Than No Message

**Role:** diagnostic-surface — an error string is read as a diagnosis, and a wrong one buys a
confident wrong fix

**First observed:** 2026-08-04, session `2026-08-04-controls-that-never-fire.md`

---

## The Finding

An error message that names a cause is treated as a diagnosis, not a guess. When the named cause
is wrong, it does not merely fail to help — it **actively redirects** the investigation, and it
does so more effectively the more specific and actionable it looks. A message offering a remedy
(`run: pip install X`) is the most dangerous form, because acting on it is cheap enough that
nobody first checks whether the premise is true.

Silence prompts investigation. A confident wrong answer prevents it.

## The concrete instance

`scripts/oversight/validators/static_analysis.py:54` emits, when its subprocess call raises:

```
"bandit not installed — run: pip install bandit"
```

The tool **was** installed — declared in `scripts/oversight/requirements.txt` and present at
`scripts/oversight/.venv/bin/bandit`. The real cause was that line 49 invokes it by bare name,
so it resolved against `PATH` and missed the venv (see
`a-decision-records-intent-not-enforcement.md`).

The message is emitted from a `FileNotFoundError` handler, so it is *technically* describing what
the process saw. But it converts "I could not resolve this" into "this is not installed", which
is a different claim about the world — and it is the claim the reader acts on.

## What it cost

The investigation that found this had, before the message was checked against reality:

- diagnosed the problem as missing provisioning
- traced it to `detect_required_tools()` covering only gate tools, not validator dependencies
- filed **#1266** as `priority:critical` with a scope of "extend the tool preflight"
- had the autonomous worker open a branch against that scope

Every step was sound reasoning from a false premise. The correction arrived only because a human
asked a question the message implicitly answered: *"should I not install bandit, so we get a firm
test?"* — which prompted checking whether it was installed at all.

Worse, the wrong fix was **self-concealing**: a preflight implemented the obvious way, with
`command -v bandit`, would also have missed the venv copy and hard-failed a correctly provisioned
machine. It would have converted a silent wrong answer into a loud wrong answer while appearing
to fix the problem.

## Implications

- **Distinguish "absent" from "unreachable" in the message**, because they have different
  remedies and only one of them is `pip install`. `"bandit not resolvable on PATH (present at
  .venv/bin/bandit?) — validators must resolve via $VENV_BIN"` costs one line and saves the
  detour.
- **A remedy in an error string is a strong claim.** Only offer one where the diagnosis is
  certain; where it is inferred, say what was observed (`FileNotFoundError invoking 'bandit'`)
  rather than what it implies.
- **Error strings are governance surface.** This one determined the scope of a `priority:critical`
  issue and the work of an autonomous agent before any human read the code. It deserves the same
  scrutiny as the logic that emits it — and it currently receives none, since no test asserts
  that a message is *true*.
- **When an error names a cause, verify the cause before acting.** Cheap, and it was the only
  step that would have caught this.

## Related

- `a-decision-records-intent-not-enforcement.md` — the underlying defect this message concealed
- `state-assertions-decay-faster-than-their-documents.md` — the same class: a confident claim
  about state, read as durable
- **#1266** — the issue whose scope this message misdirected
