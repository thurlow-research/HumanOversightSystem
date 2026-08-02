# Finding: State Assertions Decay Faster Than the Documents That Carry Them

**Role:** oversight-mechanism — a claim about current system state, once written into a durable artifact, is read as durable; its shelf life is often hours

**First observed:** 2026-08-02, session `2026-08-02-ci-execution-and-branch-rule-verification.md`

---

## The Finding

Design documents, issue bodies and runbooks mix two kinds of claim: **reasoning**, which
stays valid, and **assertions about current state** — what config is set, which files
exist, what HEAD is — which expire. They are written in the same voice, in the same
document, and rendered identically.

A reader cannot tell them apart, so the state assertions inherit the durability of the
reasoning around them. Worse, they inherit its *authority*: a state claim embedded in a
well-argued document reads as established fact, and the better the surrounding argument,
the less likely anyone is to re-run the check.

In agentic systems this compounds, because the artifacts are produced faster than the state
they describe stabilises. **Multiple agents edit the repository and its configuration
concurrently, so a document can be stale before it is finished.**

### Three instances, one day, three artifact types

**1. An issue body asserting a script does not exist.** An issue was filed specifying a new
GitHub read wrapper. `scripts/automation/lib/github.py` already implemented the reads, with
retry and rate-limit handling the new one would have lacked. Two distinct causes produced
the same wrong claim:

- The library was present in the working tree and simply not searched for.
- A second wrapper, `bootstrap/post_comment.sh`, was **absent locally and present on
  `origin/main`** — merged at 17:37, during the session that filed the issue. The clone was
  15 commits behind.

The second is the sharper one: the search was performed, and returned a confidently wrong
answer, because it ran against a stale reference.

**2. A design handoff asserting a config change had landed.** A design document stated that
a deny rule had been **removed**, and built its central argument — that removing it
re-opened a privilege-escalation path — on that state. Measured hours later:

```
$ python3 -c "…json.load(open('.claude/settings.local.json'))…"
   Edit(./bin/**)
   Edit(//home/scott/Code/HumanOversightSystem/Human/bin/**)
$ stat -c '%y' .claude/settings.local.json
2026-08-02 05:03:44 +0000
```

The file was unmodified since roughly twelve hours *before* the document was written. A
direct probe confirmed it: `touch bin/.sync-probe` → `Read-only file system`. The escalation
path the document treated as newly open had never opened.

Notably, the document's own closing section warned against exactly this — *"re-measure at
the start of each phase rather than inheriting the previous phase's observations"* — and
listed five earlier conclusions that had turned out to be artifacts. The warning did not
protect the document containing it.

**3. A repair runbook whose expected value expired mid-repair.** A step-by-step recovery
procedure specified `git log --oneline -1  # expect c17f20f or later`. Between the runbook
being written and being executed, `main` advanced 15 commits to `9ef0d13`. A human following
it literally would have seen a mismatch and been unable to tell whether the repair had
failed or the expectation had aged.

## Why this class is hard to detect

The failure is invisible at the moment of reading, which is the only moment available:

- **The document is internally consistent.** The reasoning follows from the asserted state.
  Nothing is wrong with the argument.
- **The assertion was true when written.** Reviewing the author's work finds no error, so
  review does not catch it — this is not a mistake, it is decay.
- **Re-checking is unprompted.** Nothing marks which sentences are perishable. A reader who
  re-verified every state claim in every document would do little else.
- **Confidence is inversely useful.** The stronger the document, the more it suppresses the
  question.

Note that all three instances above were caught the same way — by running a command and
reading the output — and none by reading configuration or documentation. That asymmetry is
the practical signal.

## Implication for research

Two mechanisable moves, in increasing strength:

1. **State assertions carry their provenance.** Any claim about current configuration,
   file existence or repository state should be written with the command that produced it
   and the timestamp, so a later reader re-runs rather than trusts. This costs the author
   almost nothing and converts an unfalsifiable claim into a reproducible one.

2. **Existence checks must name their reference.** "X does not exist" is meaningless without
   "as of `origin/main` at `<sha>`, fetched at `<time>`." For agent instructions this is the
   operative form: an agent told to *check whether a script already exists* will otherwise
   check its working tree, which in a multi-agent repository is nobody's current state.

The second point generalises past this finding. Agent guidance is routinely written as
*"check whether X already exists"* — and in a repository where several agents merge
concurrently, an unqualified existence check has a measurable false-negative rate. The
instruction has to specify the reference, or it produces exactly the duplicated
implementations it was written to prevent.

Relates to [`working-state-invariant`](working-state-invariant.md): there, agents build on
unverified state *between prompts within a session*. Here the same hazard operates
*between artifacts across sessions*, and the decay is faster because other agents are
committing while the document is being written.

## What changed

- **#1214** — makes "check for an existing script first" a required step, and records that
  the check must run against fetched `origin/main` rather than the working tree, since the
  latter gives a confidently wrong answer. Also proposes a *generated* script index over a
  hand-maintained one, on the grounds that a partially-stale index is worse than none: it
  implies "not listed = does not exist."
- **#1213** — corrected twice in one session as its own premises decayed, first to reuse
  `lib/github.py` rather than duplicate it, then again when `post_comment.sh` landed
  mid-session.
- Review of **#1202** returned the mechanisable version of its own method note: a design
  document asserting current configuration should carry the command that produced the
  assertion.
