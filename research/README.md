# Research Reference Materials

This directory contains curated research artifacts from the Human Oversight System project. It is distinct from `docs/` (operational documentation for users of the framework) and `scripts/` (tooling). Everything here is written for academic reference and eventual use in papers, dissertations, and research publications.

---

## Structure

```
research/
├── README.md          ← you are here
├── sessions/          ← per-session logs (one file per working session)
│   └── YYYY-MM-DD-short-title.md
└── findings/          ← durable learnings extracted from sessions
    └── finding-slug.md
```

---

## `sessions/`

One file per working session, written at the end of each session before closing. These are the "prompts as artifacts" equivalent for framework development work — a durable record of what was built, what was decided, and what was learned, written before the conversation context is lost.

**Format:**
- Date, duration, what was built
- Key decisions made and why (the reasoning that won't survive in git commits)
- Surprises — things that didn't work as expected
- Learnings — what the session revealed about the methodology
- Artifacts produced — files created or changed, linked to their commits

**Naming:** `YYYY-MM-DD-short-descriptive-title.md`

---

## `findings/`

Durable learnings extracted from one or more sessions and written in a form suitable for citing in research papers. Each finding opens with a **`**Role:**` header** classifying it on the signal/oversight axis (see `DECISIONS.md` D37): `oversight-mechanism` (the finding is about *acting on* signals — the research subject), `signal-generation` (about *producing/measuring* a signal, often a software-quality benefit rather than the oversight contribution), or `both`. The header keeps the corpus honest about which findings are the research claim and which are engineering benefits. Each finding is a standalone document that:
- States the finding precisely
- Gives the evidence (session logs, commit history, review outputs that support it)
- Explains the implication for research
- Connects to relevant literature or prior work where applicable

**When to add a finding:** When a session reveals something non-obvious about AI-assisted development governance that would stand as a research contribution on its own — not just "we fixed a bug" but "this class of bug is structurally invisible to existing review approaches."

**Naming:** `finding-slug.md` — descriptive, no date (findings are durable, not time-stamped)

---

## For the research paper

The intended citation flow:
1. **Paper claims** X about AI-assisted development governance
2. **Findings** in `findings/` provide the evidence base for X
3. **Sessions** in `sessions/` are the primary source data the findings were extracted from
4. **Git history** and **audit logs** are the underlying raw evidence
