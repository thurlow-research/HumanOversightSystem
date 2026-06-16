# Finding: One agent spec, two behavioral modes — the case against splitting interactive and autonomous into separate agent files

**Role:** oversight-mechanism — a design principle for multi-mode AI agent specifications

**First observed:** 2026-06-16, session authoring `worker.md` and `overseer.md` for the HOS runtime orchestration layer (#305, #306)

---

## The Finding

When an agent has both interactive (human present) and autonomous (cron-invoked) modes, the temptation is to create two separate agent files — one for each mode. This is usually wrong.

The routing logic, tool set, artifact-naming contracts, and sub-agent dispatch are identical across modes. What changes is (a) who initiates work, (b) what gates apply instead of human approval, and (c) which credentials are active. Splitting into two files means maintaining two specs for one role, and creates drift risk where a change to routing logic must be applied to both files and divergence is invisible until something breaks. A single spec with explicit behavioral sections documents the relationship clearly, makes the shared core obvious, and is easier to validate. Mode is determined by invocation context — a human message vs. a cron-fired `--class` flag — not by which agent file was loaded.

## Evidence

`worker.md` and `overseer.md` (this session) — each covers both interactive and autonomous modes in one file. The alternative (four files: `worker-interactive.md`, `worker-autonomous.md`, `overseer-interactive.md`, `overseer-autonomous.md`) would require a routing-logic change to be applied in two places per agent, and there is no mechanism that detects the divergence until a production failure reveals it.

## Why It Matters

This is a design principle for any multi-mode AI agent, not just HOS. The general rule: **one role = one spec file, regardless of how many invocation modes exist.** Modes are documented as explicit sections within the spec; the file boundary tracks roles, not invocation paths. The distinction is stable (a role changes rarely; invocation paths may accumulate), and a role boundary is the meaningful governance unit (you review and validate a role, not an invocation path).

The failure mode of splitting is the same class as any parallel-spec drift: two files that start identical, diverge imperceptibly, and diverge fastest in exactly the sections that matter most — the gates, the escalation conditions, the credential scoping — because those are the sections most likely to be revised under time pressure.

## Implications for Research

1. **The spec file is a governance boundary, not a code-organization boundary.** Splitting by invocation path optimizes for code organization (each file is shorter) at the cost of governance integrity (the role's full contract is visible in one place).
2. **Mode enumeration is self-documenting.** A spec with explicit INTERACTIVE and AUTONOMOUS sections makes the relationship between modes legible: shared sections state the invariants, mode sections state what varies. A reader can audit whether the modes are consistent by inspection. Two separate files have no such structure.
3. **Invocation context as the mode selector.** Mode selection at runtime (from invocation flags or message source) rather than at load time (from file choice) is the general pattern that keeps one spec viable. Systems that select behavior by file (e.g. loading a different config) must instead select by flag.

## Related findings

- `actor-identity-vs-determination-honesty.md` — the same "two properties often conflated as one" structure: here it is two invocation modes conflated as two roles.
- `the-recorder-must-not-be-in-the-recorded-set.md` — related design principle: the boundary you draw determines what falls inside and what falls outside the governance contract.
