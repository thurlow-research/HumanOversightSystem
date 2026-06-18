# Finding: 64% of rejected agentic PRs are closed with no explanation — a transparency gap that makes the system unauditable

**Role:** oversight-mechanism — auditability and audit-trail completeness; transparency of oversight decisions

**Source:** Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166, arXiv:2509.14745) — SLR P6

---

## The finding

Watanabe et al. 2026 found that **64.1% of rejected agentic PRs were closed with no explanatory comment**. There is no human-authored-code equivalent at that scale: when a human-authored PR is closed without comment, it is typically either a spam/duplicate or a clear policy violation. For agentic PRs, silent closure at this rate suggests the reviewers lack the vocabulary, time, or tooling to explain what went wrong — or do not expect the explanation to be used.

This is a transparency gap with direct consequences for oversight:

- **The agent cannot learn from rejection** if it does not know why the PR was rejected. An agent loop that can retry will retry blindly — producing the same oversized, multi-purpose, or technically-defective PR in the next cycle.
- **The human auditor cannot reconstruct the decision.** If a PR was closed silently, the audit trail shows a rejection but not the reason. Six months later, neither the team nor a researcher can determine whether the rejection was: superseded by a better PR, too large to review, technically defective, out of scope, or simply abandoned.
- **The oversight system cannot be improved** without knowing where it failed. Silent rejection is a signal that goes nowhere.

## Why it matters for scalable oversight

Auditability is a cross-cutting requirement for AI-assisted development governance — not an optional quality property. A system that closes PRs silently cannot be audited, cannot be improved, and cannot demonstrate compliance with its own oversight protocol.

This is the complement of `the-recorder-must-not-be-in-the-recorded-set.md` (the recorder must be outside the recorded system) and `explicit-na-audit-entries.md` (a skipped reviewer must emit an audited entry, not silence). The principle is the same: **silence is not a valid oversight record.** A gate that fires with no record is not a gate — it is an event that happened and cannot be referenced. A PR closure with no record is the same.

The finding also maps directly to the dissertation's auditability theme. The dissertation's claim is that HOS provides auditable oversight of AI-generated code. That claim is falsified if the system's most common oversight decision — rejecting a change — is routinely unrecorded.

## The mechanism for HOS

Every PR close/reject and every gate suspension must write a structured rationale to the audit trail. The rationale must contain:

- A **reason code** from a fixed vocabulary: `superseded` / `oversized` / `out-of-scope` / `technical-defect` / `inactive` / `other`.
- **Free text** explaining the specific ground. A reason code alone is insufficient — "oversized" does not tell the agent what the specific scope problem was.
- The **actor** (which agent or human closed the PR) and a **timestamp**.

This is not a bureaucratic overhead. It is the minimum record needed to make a PR closure auditable — to let the oversight system learn, let the agent loop improve, and let a human auditor reconstruct what happened.

HOS becomes the system in which agentic-PR rejection is never unexplained. That is a differentiating claim: a governance framework that enforces audit completeness on its own decisions, not just on the code it reviews.

## The trap it avoids

"The reviewer could see it was wrong" is not an audit record. An audit record is a committed, timestamped, structured artifact that survives the reviewer's departure from the project. The current state of agentic code review — where 64% of rejections leave no trace — means that the most informative oversight events (rejections, not approvals) are the ones most likely to be unrecorded.

## Provenance

Watanabe et al. 2026 (TOSEM, DOI:10.1145/3798166, arXiv:2509.14745). Related: `explicit-na-audit-entries.md` (silence is not a valid oversight record in any context), `the-recorder-must-not-be-in-the-recorded-set.md` (the recorder must be outside the recorded system to be trustworthy), `agentic-prs-are-larger-and-more-multipurpose-than-human-prs.md` (the same dataset; the rejection-reason gap is the downstream consequence of the size/scope problem).
