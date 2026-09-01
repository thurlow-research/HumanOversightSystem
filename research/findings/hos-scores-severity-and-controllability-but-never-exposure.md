# HOS scores severity and controllability but never exposure

**Claim:** HOS assesses risk per-change and has no representation of *how often* or *at what scale* a change class occurs. Since HOS exists to **scale** human oversight, and scaling is precisely what raises exposure, the framework omits a risk input its own purpose creates.

Source of the framing: Otten, Reis, Rigoll, Ransiek, Schürmann, Langner & Sax, *Generative AI in Systems Engineering: A Framework for Risk Assessment of Large Language Models* (arXiv:2602.04358, Feb 2026; FZI Karlsruhe, RepliCar project). Read 2026-08-15.

## The paper's useful move

The LRF classifies LLM applications on two axes — **autonomy** (0 Assisted / 1 Guided / 2 Supervised / 3 Fully Automated, explicitly modeled on SAE J3016 driving levels) and **impact** (Low / Medium / High) — then maps the pair to a risk level.

Its most substantive paragraph (§V-B) grounds this in IEC 61508 / ISO 26262:

| Safety-standard parameter | LRF equivalent |
|---|---|
| Severity | impact — harm if the output is wrong |
| Controllability | autonomy — how far a human can intervene |
| **Exposure** | **frequency or scale of use** — "rather than a property of the technical system itself" |

## What HOS already has, unnamed

HOS implements both of the paper's axes without naming either, which is why it cannot currently answer "what cell is this surface in?":

- **Severity/impact** → the risk tier (LOW→CRITICAL) from `run_validators.sh`, *plus* `protected_surfaces.txt`, which is an impact assertion that overrides computed tier ("these paths are severe regardless").
- **Controllability/autonomy** → `OVERSEER_CEILING`, and the protected-surface gate, which is functionally "for these paths, force autonomy ≤ 1: a human must approve."

So the two-axis structure is built. It is just not articulated, so it cannot be reasoned about, inventoried, or audited.

## What HOS does not have

**Exposure.** Every HOS assessment is per-change: this diff, this step, this PR. Nothing scores the *rate*. The worker fires every 10 minutes — ~144 cycles/day — and that number appears in no risk calculation anywhere.

This is not academic:

- **#1415** is an exposure failure. One cycle's leftover debris is harmless. The identical condition across four consecutive cycles (19:40–20:10, 2026-08-15) became a 40-minute outage requiring human intervention. Nothing scored "this failure recurs at cron frequency."
- **#1355** is the same shape in NG3b R2 — a deterministically-failing suite re-run repeatedly, ~4.0M agy + ~3.2M codex tokens (201% / 644% of monthly allotments) for zero new signal. Per-invocation the call was reasonable; at repetition it was not.
- An autonomy level defensible for one merge is a different proposition at 144 opportunities/day. `OVERSEER_CEILING=HIGH` is a per-PR judgement applied at a rate nobody scored.

**The irony worth recording:** HOS's stated purpose is *scaling* human oversight. Scaling is what generates exposure. So the dimension HOS omits is the one its own thesis creates.

## Three concrete implications

1. **Name the axes.** State explicitly that protected surfaces are impact-axis and `OVERSEER_CEILING` is autonomy-axis. Then "what cell is this in?" becomes answerable, and the dangerous cell (high impact × high autonomy) becomes visible rather than emergent.
2. **Add exposure as an input.** Even coarsely: is this change class produced once, per-step, or per-cycle? A LOW-tier action at cycle frequency may warrant more assurance than a MEDIUM-tier action taken once. This is genuinely new to HOS.
3. **Label every agent and gate with an autonomy level.** Today the inventory does not exist: `coder` is ~2, overseer auto-merge is 3 below the ceiling, human-proxy PR authoring is 1. Without that inventory, "where are we actually autonomous?" is unanswerable — and the trust ratchet (#1042, FABERIX §5) cannot ratchet from an unknown position.

## Using the matrix as an audit lens

Applied honestly to HOS, the LRF indicts the current configuration. Overseer auto-merge below `OVERSEER_CEILING=HIGH` is **level-3 autonomy at high impact** — the paper's red cell — for which §V-C requires "comprehensive validation, fallback mechanisms, and robust explainability... technical safeguards that prevent uncontrolled model actions."

Those fallbacks are prose. `merge_authority.py` is narrated but never executed (#1357: `python3 -c` appears zero times in any cron log). Zero bounces against 63 human-required escalations (#1358). So by the framework's own criteria, HOS's most autonomous surface is under-assured — a useful framing for the v0.7.8 Governance Enforceability milestone.

## Where the paper is weaker than HOS's own experience

**The handoff is unaddressed.** Level 2 asserts "human oversight is maintained"; level 3 that oversight "must remain possible at all times." Neither says how a human retains situational awareness at the moment control returns. Adopting the SAE analogy imports its single most notorious weakness without acknowledging it. HOS has better empirical material here — #1373 (routine HEAD advance silently resets a human's partial release authorization) is a more precisely documented handoff failure than anything in the paper.

**"Human in the loop" is treated as a control** (§V-C, twice). The 2026-08-13/14 sessions are a case study in why it is not: prose-specified human-in-the-loop that never executed while reporting success (#1357, #1358, #1362). *Every control that was code ran; every control that was prose did not.* A taxonomy that yields more prose categories is worth less here than one yielding enforceable artifacts — and the paper concedes it "does not yet provide methods to measure or quantify the maturity of a LLM application" (§VII).

## The gap worth claiming

**The LRF is a single-agent framework.** It models one LLM and one human. HOS is 26 agents reviewing each other, so autonomy is not a scalar but a **graph property**: `code-reviewer` is level 2, but its supervisor is *another model*, not a human. The LRF has no vocabulary for AI-supervising-AI — which is HOS's central mechanism. A framework that cannot express "level 2, but the supervisor is also a model" cannot classify HOS at all.

That is a clean gap for the dissertation to claim: the interesting risk surface in multi-agent oversight is **delegation depth** — how many model-mediated hops separate an action from a human — and no autonomy ladder built for single-agent assistance captures it.

## Related

- **#1042 / `docs/FABERIX-ROLES.md` §5** — the trust ratchet; the paper supplies the vocabulary it lacks.
- **#1415, #1355** — exposure failures.
- **#1357, #1358, #1362** — prose controls that never executed; the red-cell fallback gap.
- **#1373** — handoff failure better documented here than in the literature.
- Buçinca, Malaya & Gajos, *To Trust or to Think: Cognitive Forcing Functions Can Reduce Overreliance on AI in AI-assisted Decision-making*, PACM HCI 5(CSCW1), 2021, doi:10.1145/3449287 — cited by the paper as [19]. Directly relevant: NG3b R4's three-deliberate-GitHub-actions ritual **is** a cognitive forcing function, currently justified on anti-forgery grounds rather than anti-overreliance grounds. A stronger, citable argument is available for it.
- `research/findings/a-confidently-wrong-error-message-costs-more-than-no-message.md` — the diagnostic-cost pattern this paper's abstraction level cannot reach.
