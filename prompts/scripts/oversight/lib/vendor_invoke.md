# Prompt Artifact — vendor_invoke.sh (#1718 consumption guard)

| Field | Value |
|---|---|
| **Generated files** | `scripts/oversight/lib/vendor_invoke.sh`, `scripts/oversight/second_review_logic.py`, `scripts/run_second_review.sh`, `tests/oversight/test_vendor_prompt_consumption_guard.py`, `tests/oversight/test_second_review_vendor_invoke.py`, `tests/oversight/test_second_review_logic.py`, `DECISIONS.md` |
| **Description** | Per-vendor prompt byte ceiling (refuse before launch) + bytes-per-consumed-token check on the agy envelope, both failing closed (#1718) |
| **Date** | 2026-10-07 |
| **Model** | claude-opus-5-5 (worker session and coder subagent) |
| **Risk level** | HIGH (coder self-flag; shared launch primitive + mandatory pre-PR gate) |
| **Human review status** | ⬜ Pending — AR-9 product-boundary clearance required before merge |

---

## Bound design

`docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md`,
including its "Architect review (round 1)" section. Rulings AR-1 … AR-9 are
binding and override earlier TD text where they conflict.

## Prompt (coder dispatch, verbatim apart from line wrapping)

```
Implement HOS issue #1718 exactly per the architect-approved technical design
docs/v0.7.0/TECHNICAL-DESIGN-1718-vendor-prompt-consumption-guard.md (read it
fully, INCLUDING the "Architect review (round 1)" section — rulings AR-1..AR-9
are binding and override earlier text where they conflict).

Scope: the files listed in the TD's §8 file list (vendor_invoke.sh,
second_review_logic.py, run_second_review.sh, the new
tests/oversight/test_vendor_prompt_consumption_guard.py, the existing
tests/oversight/test_second_review_vendor_invoke.py adjustments per AR-8,
tests/oversight/test_second_review_logic.py, DECISIONS.md append-only entry).
Do NOT edit .claude/agents/**, scripts/framework/**, bootstrap/**, or any other
protected surface. Do NOT file issues, create labels, post comments, push, or
commit.

Key binding points:
- vendor_invoke: per-vendor byte ceiling checked BEFORE launch (agy 180000,
  codex 1048576 per AR-1), lower-only env overrides with warning on
  invalid/raising values (AR-4; refusal message names the env var when it
  lowered the ceiling), new detail prompt_too_large class harness, never
  launches the binary, new helper vendor_invoke_max_bytes as single source, new
  global recording the applied ceiling. Update the header contract comment.
- second_review_logic.py: pure consumption-check function + `consumption` CLI
  subcommand; two-way ratio computation per AR-3 (with and without
  cache_read_tokens), 6.0 bytes/token threshold, verdicts
  consumed/not_consumed/unverified, num_turns>1 -> unverified, malformed usage
  -> fail closed per TD. Decision logic in Python, not shell.
- run_second_review.sh: run_agy_review calls the consumption subcommand after
  salvage; not_consumed -> existing failure-record path with detail
  prompt_not_consumed, class vendor, consumption numbers included, no retry;
  unverified -> advisory block per AR-5 (plain fence, never json fence, never
  contains keys verdict/findings/attacks/error); prompt_too_large hint text per
  AR-2 (do NOT suggest narrowing with --files/--diff).
- Tests: every test named in TD §10, including the sentinel test with a fake
  agy stub on PATH that keeps only a prefix of stdin and still reports SUCCESS
  with proportionate input_tokens, asserting fail-closed; the never-launches
  refusal test; the verdict-identical-with-and-without-advisory test.
```

## Upstream prompts

- technical-design: produce a ≤250-line TD covering the issue's four asks
  (measure consumption, refuse oversized, decide oversized policy, sentinel
  regression test), decision logic in Python per #314, chunking deferrable to a
  named follow-up.
- architect: rule on A1–A3; verify the codex ceiling, agy blast radius, the 6.0
  threshold and cache-token semantics, lower-only overrides, and the advisory's
  verdict-neutrality against the actual code.

## Refinement history

1. TD proposed a 180,000-byte ceiling for codex as well. Architect (AR-1) rejected
   it with evidence: codex's measured limit is 1 MiB (#1384), it errors rather than
   truncating, and 180 KB would break working codex lanes (~417–730 KB).
2. Architect (AR-3) replaced always-add-cached-tokens with a two-way reading,
   because the only fixture cannot settle whether `input_tokens` already includes
   `cache_read_tokens`.
3. Architect (AR-8) found a second 200 KB test the TD missed; both were shrunk to
   150 KB, which still sits above MAX_ARG_STRLEN.
