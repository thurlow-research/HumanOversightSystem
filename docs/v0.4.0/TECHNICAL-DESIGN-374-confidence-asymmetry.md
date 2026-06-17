# Technical Design — SPEC-374: Confidence Asymmetry Rule

**Document type:** Technical design (coder-ready; contract, not implementation)
**Issue:** #374
**Spec:** `docs/specs/SPEC-374-confidence-asymmetry.md`
**Architect status:** GO received (rulings OQ-374-01/02/03 binding, recorded in §0)
**Author:** technical-design
**Date:** 2026-06-16

---

## 0. Binding architect rulings (carried into the contract)

| Ruling | Decision | Where it lands in this design |
|---|---|---|
| **OQ-374-01** | Exclusion-by-construction is primary. ADD one compliance check: the evaluator FAILS if any `human-tier-override.md` or `human-authorization.md` cites confidence as the justification for a tier reduction or reviewer waiver. | §4 (evaluator check C-374), §3 (locus decision) |
| **OQ-374-02** | The evaluator must NOT emit a `CONFIDENCE:` field. The field stays confined to authoring-agent self-flag blocks. | §4b (explicit prohibition text) |
| **OQ-374-03** | Static analysis (grep) is the primary verifier for prompt paths. Add ONE behavioral invariance test for any executable routing path. | §5 (tests) |

These are fixed inputs. This design does not reopen them; it specifies how each is realized.

---

## 1. Component map

The change touches **four** artifacts. Three are prose-contract edits (agent/protocol Markdown); one is a behavioral test asset. No application code path in the orchestrator, risk-assessor, or evaluator is *modified* — the routing exclusion is enforced by the *absence* of a confidence read, which the tests assert.

| # | Component | File | Change class | Type |
|---|---|---|---|---|
| C1 | Confidence asymmetry rule text | `AGENTS.md` (§3 Confidence Declaration) | additive | Prose contract |
| C2 | Evaluator Phase 2 finding-independence note | `.claude/agents/oversight-evaluator.md` | additive | Prose contract |
| C3 | Evaluator self-declaration prohibition | `.claude/agents/oversight-evaluator.md` | additive | Prose contract |
| C4 | Evaluator compliance check C-374 (confidence-as-justification scan) | `.claude/agents/oversight-evaluator.md` Phase 1 | additive | Prose contract + bash snippet |
| T1 | Grep assertions (routing-exclusion + text-presence) | new test file (see §5.1) | additive | Test |
| T2 | Behavioral invariance test (routing path) | new test file (see §5.2) | additive | Test |

**Dependency order for the coder:** C1 → C2 → C3 → C4 → T1 → T2. C4 must be written before T1 because one grep assertion targets C4's own snippet (it must read the artifacts but never *act* on confidence to lower a tier).

**What this design does NOT change** (locked by spec REQ-374-06/07/09/10 and §5 of the spec):
- The `CONFIDENCE:` self-flag format/schema — unchanged.
- `contract/OVERSIGHT-CONTRACT.md` §2 (self-flag format) and §7 (compliance conditions 1–10) — no new schema, no new numbered compliance condition. C-374 is a *behavioral constraint on interpretation*, recorded as evaluator-prompt text, not a new contract condition number.
- The existing Phase 2 "Confidence gaps" check (CONFIDENCE < 70% on HIGH+) — unchanged; preserved verbatim. T1 asserts its survival.
- How any agent computes/reports confidence — unchanged.

---

## 2. C1 — AGENTS.md asymmetry rule (exact wording and position)

### 2.1 Contract

**Position.** The rule is appended **inside** the existing `### 3. Confidence Declaration` section, immediately **after** the existing "Be honest…" paragraph (current `AGENTS.md` line 133) and **before** the `### 4. Hallucination Surface Warning` heading (current line 136). It must be contiguous with the `CONFIDENCE:` format block so it reads as part of the same requirement (spec REQ-374-04, AC-374-01). It is NOT a new top-level section.

**Required content** — the text must name all four spec-mandated elements (a)–(d) of REQ-374-04. The coder writes the following block exactly:

```markdown
#### Confidence is one-directional (the asymmetry rule)

A declared confidence value is a signal to the **human reader only**. It calibrates
where a person spends attention before reading the code; it carries **no routing
authority** in the pipeline.

- **Prohibition.** High confidence MUST NEVER lower a risk tier below what the risk
  rubric and deterministic validators assign, remove or skip a required reviewer, or
  substitute for any gate (deterministic — lint, type, security scanner — or manual —
  human authorization).
- **Enforcement (by construction).** Confidence is **excluded from every automated
  routing decision and tier assignment.** No code path in the orchestrator,
  risk-assessor, or oversight-evaluator may read the `CONFIDENCE:` value to reduce the
  required sign-off set, lower a tier, or suppress a finding. The exclusion is
  structural — there is no confidence-reading branch to disable.
- **Empirical basis.** Self-reported agent confidence does not predict defects
  (Ferdous et al. 2026, MSR): 99.9% of agent PRs self-report confidence in the 8–10
  band, and the defect rate across that band is flat — 3.16% (8), 3.51% (9), 3.96%
  (10). A signal that is saturated and uncorrelated with the outcome cannot
  discriminate risk, so using it to reduce oversight buys no safety and opens a
  manipulation surface (inflate the number to shed reviewers).
- **Direction.** Low confidence remains a valid signal **upward** — a 40%-confidence
  declaration on HIGH-risk code is a meaningful flag for human attention (and is what
  the evaluator's Phase 2 "Confidence gaps" check surfaces). High confidence carries
  no authority **downward**: it never reduces oversight.
```

### 2.2 Boundaries

- The coder must NOT edit or reword the existing `CONFIDENCE:`/`Basis:` format block or the "Be honest…" paragraph. Additive only.
- The empirical figures (99.9%, 3.16/3.51/3.96%) are load-bearing for AC-374-01 and must appear verbatim.

---

## 3. Compliance-check locus decision (deliverable item 3)

**Question:** does C-374 (scan human-authorization artifacts for confidence-as-justification) live in the evaluator's CORE prompt as an instruction, or as a Python script the evaluator invokes?

**Decision: CORE prompt instruction with an inline `grep` pre-filter, NOT a new Python script.** Rationale (this is a design/locus decision within technical-design's domain, not an architecture decision):

1. **The artifacts are unstructured human prose.** `human-tier-override.md` and `human-authorization.md` have no parseable schema for "the justification" — they are free-text human decisions (confirmed: the only structured field is `authorized_by:`; everything else is prose, per `gate-suspension.template.md` and the evaluator's existing `grep -m1 -i '^authorized[ _]by:'`). A Python script could only do the same substring match a `grep` does; it cannot semantically determine that "confidence" is being used *as the justification* vs. mentioned incidentally ("I have full confidence in proceeding"). Adding a script would imply a precision the parse cannot deliver and creates a new fail-closed dependency (another script that can error on a MEDIUM+ step).

2. **Architect ruled grep is the primary verifier (OQ-374-03).** A bash `grep` pre-filter inside the existing Phase 1 flow is consistent with that ruling and with how the evaluator already reads these files (it already greps them for `authorized_by`). The evaluator is an LLM agent; the *semantic* disambiguation (does this prose cite confidence as the reason?) is exactly the judgment an agent prompt is for, gated by a cheap deterministic pre-filter that decides whether the judgment is even needed.

3. **Two-stage check, fail-toward-human:** the `grep` is a *trigger*, not the verdict. If the token is absent → pass (no human ever cited confidence). If present → the evaluator reads the surrounding prose and decides FAIL vs. incidental; an ambiguous case is treated as FAIL (ratchet: a confidence-justified waiver loosens oversight, so uncertainty fails closed). This keeps a false "confidence" mention from auto-failing while ensuring a real one cannot pass.

**Consequence:** No file under `scripts/oversight/` is created or modified for C-374. The check is entirely C2/C3/C4 prose in `oversight-evaluator.md`. (T2's invariance test still needs a harness; see §5.2 for where that lives — it tests the *routing-exclusion* invariant, a separate concern from C-374.)

---

## 4. C2/C3/C4 — oversight-evaluator.md changes

### 4a. C2 — Phase 2: high confidence must not deprioritize findings

**Position.** In `## Phase 2 — Quality evaluation`, inside the existing **Confidence gaps** bullet group (current `oversight-evaluator.md` lines 183–185), appended as a new bullet immediately after the existing `Any CONFIDENCE < 70% on HIGH+ files…` line. Keeps the asymmetry note adjacent to the check it qualifies (spec §5, REQ-374-05).

**Exact text to add:**

```markdown
- **Confidence is one-directional (SPEC-374).** A finding is a finding regardless of
  the authoring agent's declared confidence. You MUST NOT suppress, downgrade, or
  deprioritize any Phase 2 finding (convergence failure, critical-finding-resolved,
  second-review flag, confidence gap) because the agent declared high confidence. In
  particular: a CONFIDENCE < 70% flag on a HIGH+ file is NOT dismissed because another
  part of the diff carried high confidence, and you do NOT infer reduced human-review
  urgency from a high confidence value. High confidence carries no authority to lower
  scrutiny; only low confidence is a signal — and it points upward, to the human.
```

**Boundary:** the existing `CONFIDENCE < 70% on HIGH+` bullet (REQ-374-08, AC-374-05) is preserved exactly — do not delete or reword it. C2 is additive beneath it.

### 4b. C3 — evaluator must NOT emit a CONFIDENCE field (OQ-374-02)

**Position.** In the `## What you do NOT do` list at the end of `oversight-evaluator.md` (current lines 296–303), as a new bullet.

**Exact text to add:**

```markdown
- Do not emit a `CONFIDENCE:` field in your evaluation, sign-off notes, or response.
  The `CONFIDENCE:` self-flag belongs to **authoring agents only** (AGENTS.md §3); you
  are an assessing agent, not an authoring one. Your output is a recommendation
  (PROCEED / CONDITIONAL_PROCEED / ESCALATE) with reasoning — not a confidence
  declaration. Emitting one would create exactly the saturated, uninformative routing
  signal SPEC-374 prohibits, one level up.
```

**Boundary:** This is the full scope of OQ-374-02. The evaluator's existing output schema (§Output, the evaluation `.md` template) already has no `CONFIDENCE:` field; C3 makes its absence a stated prohibition so a future edit cannot reintroduce it. The coder must NOT add a confidence field anywhere in the evaluator's output template.

### 4c. C4 — compliance check: confidence-as-justification scan (OQ-374-01)

**Position.** In `## Phase 1 — Compliance check`, as a new check appended **after** the `Structural-override verification (#75)` block (current line ~146) and **before** the `Second-review compliance` block (current line 147). Reason: it belongs with the other "loosening-direction" anti-gaming checks (N/A verification, structural-override) — all three guard the human-authorization boundary.

**Algorithm (the contract — what the check must do):**

1. **Scope:** runs only when at least one of these human-authored artifacts exists for this step:
   - `.claudetmp/oversight/step{N}-human-authorization.md`
   - `.claudetmp/oversight/human-tier-override.md`
   - any domain structural-auth file (`.claudetmp/oversight/step{N}-*-structural-auth.md`)
   - `contract/gate-suspension.md` (a reviewer-waiver artifact)

   If none exist → no human cited anything → check is N/A, pass. (No artifact, no possible confidence-justification.)

2. **Deterministic pre-filter (grep trigger):** for each existing artifact, case-insensitive search for the token `confidence`:
   ```bash
   for f in .claudetmp/oversight/step{N}-human-authorization.md \
            .claudetmp/oversight/human-tier-override.md \
            .claudetmp/oversight/step{N}-*-structural-auth.md \
            contract/gate-suspension.md; do
     [ -f "$f" ] || continue
     grep -in 'confidence' "$f" && echo ">>> review $f"
   done
   ```
   - **No match in any artifact → PASS** (record: "C-374: no confidence token in any human-authorization artifact").

3. **Semantic disposition (agent judgment, only on a match):** for each matched line, read the surrounding prose and decide whether confidence is being **cited as the justification** for the tier reduction / reviewer waiver, i.e. the human's stated *reason* is the agent's (or anyone's) declared confidence. Decision rule:
   - The justification **is** confidence (e.g. "lowering to MEDIUM because the coder reported 95% confidence", "waiving security review — agent confidence was high") → **COMPLIANCE FAIL**. List the artifact, line number, and the quoted justification. This is the asymmetry violation OQ-374-01 forbids: confidence used downward to loosen oversight, laundered through a human artifact.
   - The mention is **incidental** and NOT the basis of the loosening (e.g. "I am confident this brownfield exception is correct", "confidence in the rollback plan") → **PASS**, but record the matched line in the evaluation notes so a reader can audit the judgment.
   - **Ambiguous** (cannot tell whether confidence is the operative reason) → **COMPLIANCE FAIL** (ratchet: loosening under uncertainty fails closed). State why it was ambiguous.

4. **On FAIL:** recommendation is **ESCALATE**; the escalation item names the artifact, the quoted confidence-as-justification text, and states the required fix: *"Re-author the human-authorization with a justification that does not rest on declared confidence (SPEC-374 / AGENTS.md §3 asymmetry rule). Confidence may not justify a tier reduction or reviewer waiver."*

5. **Audit event:** on a FAIL, append to `audit/oversight-log.jsonl`:
   ```
   {"event":"confidence-justification-rejected","step":N,"artifact":"{file}","evidence":"{quoted line}","timestamp":"..."}
   ```
   (No new event needed on PASS; the evaluation `.md` records the cleared check.)

**Exact prose to add to the evaluator (the coder transcribes this, adjusting the bash to match house style):**

```markdown
**Confidence-as-justification scan (SPEC-374 / OQ-374-01) — runs whenever a human-authored
loosening artifact exists for this step:** Confidence is one-directional (AGENTS.md §3):
it may never justify lowering a tier or waiving a reviewer. A human-authorization artifact
that *grounds its loosening decision in declared confidence* re-introduces the prohibited
downward use through the human gate. Scan for it.

1. Scope: run only if at least one of these exists —
   `.claudetmp/oversight/step{N}-human-authorization.md`,
   `.claudetmp/oversight/human-tier-override.md`,
   `.claudetmp/oversight/step{N}-*-structural-auth.md`, or `contract/gate-suspension.md`.
   If none exist → N/A, pass.
2. Deterministic pre-filter: case-insensitive `grep -in 'confidence'` each existing artifact.
   No match anywhere → PASS (record "no confidence token in loosening artifacts").
3. On a match, read the surrounding prose and judge whether confidence is cited *as the
   reason* for the tier reduction or reviewer waiver:
   - It is the operative justification → **COMPLIANCE FAIL** (list artifact, line, quoted text).
   - Incidental mention, not the basis of the loosening → PASS, but record the line in the
     evaluation notes for audit.
   - Ambiguous → **COMPLIANCE FAIL** (loosening under uncertainty fails closed — the ratchet).
4. On FAIL: ESCALATE. Escalation item names the artifact + quoted text and requires the human
   to re-author a justification that does not rest on declared confidence. You may NOT edit the
   artifact yourself (Human authorization file integrity prohibition applies).
5. On FAIL, append to `audit/oversight-log.jsonl`:
   `{"event":"confidence-justification-rejected","step":N,"artifact":"{file}","evidence":"{line}","timestamp":"..."}`.
```

**Boundaries / things the check must NOT do:**
- It must NOT read or use the agent's `CONFIDENCE:` *value* to make any routing decision — it only inspects human-authored *prose* for whether confidence was *cited*. (T1 grep asserts C4 introduces no confidence-value read into the routing path.)
- It must NOT create, edit, or delete the human-authorization artifact (existing `Human authorization file integrity` prohibition, line 268 — absolute). The only output on a problem is ESCALATE.
- It is NOT a new numbered §7 compliance condition (spec REQ-374-06). It is an additional Phase 1 check in the evaluator prompt only; `contract/OVERSIGHT-CONTRACT.md` §7 is untouched.

---

## 5. Tests (deliverable item 4)

### 5.1 T1 — grep assertions (OQ-374-03 primary verifier)

**Purpose:** AC-374-02 (routing exclusion) and AC-374-01/03/04/05 (text presence/preservation), verifiable by static analysis — the primary verification mechanism per OQ-374-03.

**Location:** `tests/spec_374/test_confidence_asymmetry_static.py` (a static-text assertion suite; no runtime imports of pipeline code — it greps repo files). If the project has an existing framework-doc test home, the unit-test agent may place it there; the assertions below are the contract.

**Assertion set — routing-exclusion greps (AC-374-02, AC-374-03):**

For each routing-path agent file — `.claude/agents/oversight-evaluator.md`, `.claude/agents/oversight-orchestrator.md`, `.claude/agents/risk-assessor.md`:

| ID | What to grep | Files | Pass condition |
|---|---|---|---|
| T1-a | Any instruction reading a `CONFIDENCE:` *value* to **lower a tier / remove a reviewer / reduce sign-offs** | the three routing-path agent files | **Zero matches** for risk-lowering use. Confidence may appear ONLY in (i) the Phase 2 low-confidence flag bullet, (ii) the §C2 asymmetry note, (iii) the §C4 scan, (iv) the §C3 prohibition. A grep for `confidence` in these files, minus those four allowed contexts, finds no branch that uses the value to reduce oversight. |
| T1-b | The evaluator emits no own `CONFIDENCE:` field (OQ-374-02 / AC) | `oversight-evaluator.md` Output template | The evaluation `.md` template contains no `CONFIDENCE:` line; the §C3 prohibition bullet IS present. |

Concrete grep the test runs (illustrative — the contract is "no risk-lowering confidence read"):
```bash
# Must find the asymmetry note, prohibition, and scan (presence):
grep -q 'one-directional' .claude/agents/oversight-evaluator.md
grep -q 'Do not emit a `CONFIDENCE:` field' .claude/agents/oversight-evaluator.md
grep -q 'Confidence-as-justification scan' .claude/agents/oversight-evaluator.md
# Must NOT find confidence used to lower a tier / drop a reviewer (exclusion):
! grep -iE 'confidence.*(lower|reduce|skip|waive|remove).*(tier|review|sign-?off)' \
    .claude/agents/oversight-orchestrator.md .claude/agents/risk-assessor.md
```

**Assertion set — text-presence greps:**

| ID | AC | Files | Pass condition |
|---|---|---|---|
| T1-c | AC-374-01 | `AGENTS.md` | §3 contains "asymmetry rule" wording + the empirical figures `99.9%`, `3.16%`, `3.96%`, and names "Ferdous et al. 2026". |
| T1-d | AC-374-04 | `AGENTS.md` | The `CONFIDENCE:` self-flag format block still present (field not removed). |
| T1-e | AC-374-05 | `oversight-evaluator.md` | The `CONFIDENCE < 70%` Phase 2 bullet still present (low-confidence flag preserved). |

### 5.2 T2 — behavioral invariance test (the one executable-routing test, OQ-374-03)

**Purpose:** OQ-374-03 requires exactly one behavioral invariance test for an *executable* routing path. Among the three routing-path components, the only one with deterministic *executable* code (not prose) is the change-classifier the evaluator invokes; the orchestrator and risk-assessor routing is prose-driven (covered by T1 static greps). The executable invariant we can assert is: **a deterministic routing/classification tool's output does not depend on a `CONFIDENCE:` value present in the diff or commit.**

**Location:** `tests/spec_374/test_confidence_routing_invariance.py`.

**Test contract:**

- **Subject under test:** `scripts/oversight/change_classifier.py` (the deterministic, executable component on the routing path the evaluator drives).
- **Input that VARIES:** two otherwise-identical diffs/commit ranges that differ ONLY in a `CONFIDENCE:` line in the self-flag block / commit body — e.g. fixture A carries `CONFIDENCE: 40%`, fixture B carries `CONFIDENCE: 99%`, all other content byte-identical.
- **Output that MUST be IDENTICAL:** the classifier's JSON output — `domains_touched` and `structural_signals` (and exit code). Assert `output_A == output_B`. The varying confidence value changes nothing about which domains are touched or whether the change is structural.
- **Why this is the right invariant:** it proves the executable routing/classification decision is *blind* to confidence — the by-construction exclusion (REQ-374-02) holds not just in prose but in the one place real code makes a routing-relevant determination. A regression that ever made the classifier read confidence would flip this test red.

**Note for the unit-test agent:** if `change_classifier.py` genuinely never tokenizes commit bodies (confidence lives in the self-flag, which the classifier may not even read), the test still must exist as a *guard* — it pins the invariant so a future change that starts reading commit bodies cannot silently introduce a confidence dependence. State that framing in the test docstring. This satisfies OQ-374-03's "one behavioral invariance test for any executable routing path."

---

## 6. Traceability matrix (every AC has an owner)

| Acceptance criterion | Realized by | Verified by |
|---|---|---|
| AC-374-01 (AGENTS.md asymmetry text + figures) | C1 | T1-c |
| AC-374-02 (routing exclusion, static) | by-construction (no edit) | T1-a, T2 |
| AC-374-03 (evaluator Phase 2 finding independence) | C2 | T1-a, code review of C2 |
| AC-374-04 (CONFIDENCE field not removed) | C1 boundary (additive only) | T1-d |
| AC-374-05 (low-confidence flag preserved) | C2 boundary (existing bullet kept) | T1-e |
| OQ-374-01 (confidence-as-justification check) | C4 | review of C4; runtime exercise on a crafted artifact |
| OQ-374-02 (evaluator emits no CONFIDENCE) | C3 | T1-b |
| OQ-374-03 (grep primary + 1 invariance test) | T1 (grep) + T2 (invariance) | both present |

---

## 7. Startup-artifact-gap analysis

**Question (per the startup-gap protocol): should this have been settled in the initial technical design, before any code was written against it?**

**No — this is a genuine additive hardening, not a late correction of an existing contract.** The asymmetry rule closes a *gap of omission*: the original protocol specified the `CONFIDENCE:` field and said "be honest" but never specified what downstream actors may do with it (spec §1). No prior code was written that *relies on* confidence to route — the exclusion already held by construction (there is no confidence-reading routing branch to remove). T1-a's static grep over the current routing-path files is the evidence: if it passes on the *unmodified* files, the by-construction guarantee predates this spec.

**Affected sign-offs analysis:**
- **No prior sign-off is invalidated.** No already-approved code is being re-contracted; the downward use was never built, so there is no orphaned approval to re-audit. This is the "missing edge case never exercised → prior sign-offs stand" case, not the "changed contract for built behavior → re-review" case.
- If T1-a *fails* on the unmodified files (i.e. some routing branch DOES read confidence to loosen oversight), that flips this to a startup-artifact-gap: open the issue, and the sign-off on whatever component contains that branch must be flagged for re-review against the corrected contract. **The coder must run T1-a against the pre-change tree first and report the result.** (Expected: passes clean.)

---

## 8. Self-flag

```
RISK: MEDIUM
```

Business-logic / governance-contract change to the oversight pipeline's interpretation rules. No application data flow, no auth, no destructive op — but it edits the protocol that governs every build step's routing, so it is above LOW.

**Change classification:** `additive`. Every component (C1–C4, T1–T2) adds contract text or tests; nothing rewrites an existing contract or removes a field/check. Not `structural` — no new external dependency, no new permission/auth state, no new user-facing surface, no new routing branch (the routing exclusion is realized by *absence*). Therefore no human pre-authorization gate is triggered for the design itself.

## Human Review Required

**§3 — Compliance-check locus decision (CORE prompt + grep, not a Python script)**
Review for correctness: I ruled the confidence-as-justification scan lives in the evaluator prompt with a grep pre-filter, not as a `scripts/oversight/` script, because the artifacts are unstructured human prose and a script could only do the same substring match while adding a fail-closed dependency. Confirm this matches the architect's intent for OQ-374-01 (the ruling said "ADD one compliance check" without specifying the locus). If the architect expected a deterministic script, this is the point to redirect — it is the one place I exercised design discretion on the architect's behalf.

**§4c step 3 — semantic disposition is agent judgment, with ambiguous→FAIL**
Review for correctness: the FAIL/PASS decision on a matched "confidence" token is an LLM judgment (operative justification vs. incidental mention), with ambiguous cases failing closed. Verify the ratchet framing is acceptable: a false positive forces a human to re-author an authorization (friction, safe); a false negative would let a confidence-justified waiver through (the failure mode we are preventing). The ambiguous→FAIL bias is deliberate.

**§5.2 — T2 invariance subject is `change_classifier.py`**
Review for correctness: I selected the change-classifier as the single executable routing path for OQ-374-03's behavioral test because orchestrator/risk-assessor routing is prose-driven (covered by static greps). If the project considers another component the canonical "executable routing path," the unit-test agent should retarget — but the invariant (output identical under varying confidence) is the contract regardless of subject.

CONFIDENCE: 80%
Basis: Confident on C1–C3, the traceability matrix, and the test contracts — they are direct transcriptions of spec ACs and binding architect rulings. Less certain on the §3 locus decision and the §5.2 test subject: both are design discretion the architect's rulings left open, and either could be redirected on review without changing the rule's substance.
```

---

## 9. Open questions for the architect (flagged, not resolved here)

These do not block the coder on C1–C3 and T1, but the architect should confirm before C4 and T2 are signed off:

- **OQ-TD-374-A (C4 locus):** Confirm the CORE-prompt + grep locus for the confidence-as-justification scan (§3) satisfies OQ-374-01, vs. a deterministic Python script under `scripts/oversight/`. My reasoning: artifacts are unstructured prose; a script adds a fail-closed dependency without added precision. **If the architect wants a script, that is an architecture-of-the-check decision and I will revise §3/§4c.** Routed to `architect`.

- **OQ-TD-374-B (T2 subject):** Confirm `change_classifier.py` is the intended "executable routing path" for OQ-374-03's one invariance test, given orchestrator/risk-assessor routing is prose. If the project has another executable routing component in scope, name it and I will retarget T2.

- **OQ-TD-374-C (gate-suspension.md in C4 scope):** I included `contract/gate-suspension.md` in C4's scanned-artifact set because a reviewer waiver justified by confidence is exactly the prohibited downward use, and suspension is a reviewer-waiver artifact. The spec's OQ-374-01 text names only `human-tier-override.md` and `human-authorization.md`. Confirm the broader set is acceptable (it is strictly more scrutiny — the ratchet direction) or constrain C4 to the two named files. Routed to `architect`.

---

## 10. Status

**Status: DRAFT — architect review requested.** Per the iteration protocol this design does NOT go to the coder until the architect approves. Iteration 1. Architect: please rule on OQ-TD-374-A/B/C and confirm C1–C4 + T1–T2 close every spec AC.
```