# Finding: Refactoring an Artifact to a Reusable/Layered Form Is a Quality Audit of the Original — It Surfaces Both Hidden Coupling and Hidden Gaps

**Role:** oversight-mechanism — why the CORE/PACK/PROJECT layering (and the "borg" extraction) does more than reorganize; it *audits*.

**First observed:** 2026-06-15, the v0.3.0 django-pack borg — extracting the Django-reusable depth out of the pilot consumer's hand-rolled agents into `packs/django/`, separating universal (`CORE`) from stack-reusable (`PACK`) from project-unique (`PROJECT`).

---

## The Finding

The borg's *stated* purpose was reorganization: pull reusable Django depth into a pack so `core + pack ≈ the consumer's agent`. But the act of deciding, per line, "is this universal, stack-reusable, or project-unique?" turned out to be a **forcing function that audited the source agents** — it surfaced two opposite defects that a flat agent completely hides:

1. **Hidden coupling — content that *looked* generic but wasn't.** The `architect` and `technical-design` packs, written to be "generic Django," shipped with CPS-domain example nouns baked into the guidance (`Booking`, `earned-horizon`, `HOA portal`, `operator console`, `AuditLog.scrub()`). In the original flat agent these read as harmless illustrations. The moment the content had to be labeled "reusable by *any* Django project," the coupling became visible and wrong — those examples are noise (or worse, misdirection) for the *next* Django consumer. We caught it only because layering forced the "is this generic?" question on every line.

2. **Hidden gaps — content that *should* have been there but wasn't.** The `privacy-reviewer` borg revealed the consumer's hand-rolled privacy-reviewer was **thin** — it had a CPS-specific PII inventory but almost no reusable Django privacy *mechanics* (encrypted fields, `on_delete` erasure cascades, `.values()/.only()` leakage, DRF serializer exposure, `RunPython` migration PII). Extracting "the Django-reusable privacy depth" surfaced that there was barely any — the original was under-specified. The pack filled it to a complete Django standard.

So the same operation surfaced **over-coupling in one agent and under-specification in another** — opposite failure modes, both invisible until the artifact was forced into a reusable shape.

## Why This Happens

You don't actually understand what's essential vs incidental about an artifact until you try to **reuse it in a second context.** A flat artifact written for one consumer conflates three things — the universal obligation, the stack pattern, and the project specific — and nothing forces them apart. Layering (CORE/PACK/PROJECT) is that forcing function: every sentence must be assigned an ownership layer, and mis-assigned content (a project-specific example in a "generic" layer) or missing content (a thin layer that should be rich) becomes a *decision you have to make*, not a thing you can skip.

This is the well-known SWE truth — "the second use is when you learn the abstraction" / "you don't know your API until you have two callers" — applied to **agent definitions and oversight artifacts** rather than code.

## Why It Matters for Oversight

- **The layering is not free reorganization; it is a review pass.** Budget for it as one. The v0.3.0 borg's per-agent "is this generic?" discipline caught domain-leak in 2 of 12 packs and under-specification in at least 1 — defects that survived these agents' entire prior life as flat files.
- **It predicts where to look on the *next* pack.** When a third stack (or a second Django consumer) is borg'd, expect the extraction to again surface (a) "generic" content that's secretly coupled to the first consumer's domain, and (b) lanes the first consumer under-built. Audit aggressively at the layer boundary.
- **It is a one-time-per-artifact dividend.** Once an agent is cleanly layered, the audit is banked; future edits stay within a layer. The cost is paid at the refactor, the value compounds.

## Process note

The discipline that operationalized this: a **CPS-proper-noun grep on every PACK body before commit** (`parkshare|HOA|earned-horizon|Booking|AuditLog|...`), distinguishing genuine generic patterns (`tstzrange`, VAPID, TOTP — keep) from domain leaks (generalize). The grep is the cheap deterministic half; the "is this generic enough?" judgment is the agent/human half — the gates-and-review split again.

## Related findings

- `hos-ports-human-best-practices.md` — "extract a shared library / find the abstraction on the second use" is standard human SWE practice; here ported to agent artifacts.
- `gates-and-review-are-complementary.md` — the proper-noun grep (deterministic) + the "is it generic?" judgment (review) split the audit cleanly.
- `design-review-catches-failclosed-invariants.md` — same session; both are "the structured process surfaces what the flat artifact hid."
