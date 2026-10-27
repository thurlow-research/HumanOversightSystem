# Finding: a proxy's draft of the human's ruling is mistaken for the human's act, by the human

**Role:** oversight-mechanism. The provenance of a human authorization is part of the human gate, and an AI proxy's drafting can blur it even for the authorizer.

**Evidence strength:** a single observed incident with a clear mechanism. Recorded as a finding because the failure was caught only by an explicit verification step, and the mechanism generalises to any proxy-drafted authorization. Before this is cited as a pattern, it needs corroborating incidents.

**Source:** HOS session, 2026-10-20, `thurlow-research/HumanOversightSystem` #2100

---

## The finding

In HOS a ruling on an escalation must be posted **from the human's own GitHub account**. The worker ignores rulings posted by the human-proxy's bot identity (ARCH-ESC-6). The human-proxy (an AI session acting for the human) therefore posts a clearly labelled *relay* comment describing the proposal, and gives the human a paste-ready line to post themselves.

On 2026-10-20, for #2100, the relay comment included that paste-ready line **verbatim** in a quote block, under a heading that said it was for the human to post. The human read the issue and saw the exact text of the ruling in the thread. They concluded they had posted it, and removed the `needs-human` label, which releases the issue to the autonomous worker.

They had not posted it. The only copy of the ruling on the issue was the proxy's. The gap was caught when the human-proxy, asked to confirm, listed the human's own-account comments and found the amendment missing. The human's own explanation was: "I saw your comment and thought I had done it." Had the worker picked up the issue in that window, it would have built the original design, which falls back to `/tmp` silently, against the human's intent. It would also have treated the issue as cleared by the human.

## Why it matters for scalable oversight

Human-gate designs usually defend against *others* forging the human's authorization: bots, compromised accounts, self-approving agents (see `actor-identity-vs-determination-honesty.md`). This incident is a different failure: **the authorizer loses track of their own act.**

- **Recognition is not recall.** Seeing the right words in the thread produces a feeling of familiarity ("that's my ruling"). That feeling is not evidence that *I* posted it. A proxy that drafts in the human's voice puts that familiarity cue exactly where the human looks to check.
- **The identity rule saved the outcome, but only with verification.** ARCH-ESC-6 made the proxy's copy non-authoritative. Even so, removing the label is itself a human act the worker treats as clearance, and it went ahead on the false belief. The identity control protected the *ruling*. It did not protect the *label*, which is a second, weaker authorization signal.
- **Scaling makes this worse.** The more a proxy drafts on the human's behalf, which is the point of a proxy, the more of the human's apparent record was written by someone else.

## The mechanism for HOS

- **Relay comments carry no paste-ready ruling text.** They describe the proposal and state that the human will confirm from their own account. The exact line exists only in the private channel between the human and the proxy, so the only copy on the issue is the human's.
- **Verify before treating an issue as ruled.** When the human says "done," the proxy checks that an own-account comment exists before reporting the issue as ruled.
- Both rules were added to the human-proxy's permanent-instructions work (#2102). The longer-term structural answer is GitHub-native authorization with a deterministic verifier (#2101): only a prescribed-form comment by a verified human CODEOWNER counts, and label removal alone never does.

## The trap it avoids

"The human was in the loop" assumes the human knows which acts in the loop are theirs. When an AI proxy writes in the human's voice, that assumption needs a mechanism behind it. An authorization record must be distinguishable by its *author* at a glance, not only by its *content*. Otherwise the human can rubber-stamp their own proxy without noticing.

## Provenance

HOS human-proxy session 2026-10-20 (session log `../sessions/2026-10-20-core-first-unblock-and-escalation-redesign.md`). Issue #2100: relay comment 2026-10-20 18:27 UTC; the label was removed shortly afterwards; the human's own-account amendment was posted at 18:34 UTC, after the proxy's verification found it missing. Related: `actor-identity-vs-determination-honesty.md`, `human-gate-enforcement-limits.md`, `self-classification-cannot-gate-the-human-boundary.md`.
