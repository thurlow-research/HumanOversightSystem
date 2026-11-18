# Gate Suspension — dep-mapper LOW (time-boxed, #2214)

<!--
  PROVENANCE: drafted by the worker under the explicit human ruling quoted in
  Reason below, per the #2170 human-interface rule. The authorization is the
  CODEOWNER (ScottThurlow) approval of the PR that adds this file; the human
  wrote no file. Agents must not otherwise create or modify this file. To end
  the suspension early, a human removes the SUSPENDED line (or deletes the file)
  via an approved PR. It also stops suppressing on its own: from 2027-01-01 UTC,
  or as soon as #2162 is closed as completed (scripts/oversight/suspension_manager.py
  --suspension-status dep-mapper).
-->

Authorized by: ScottThurlow (CODEOWNER approval of the PR that adds this file)
Date: 2026-10-30
Approving PR: the merged PR that adds this file (Part of #2214); its number is the "(#<n>)" suffix of the adding commit — git log --diff-filter=A -- contract/gate-suspension.md
Reason: Human ruling on #2174, 2026-10-30, Q1 B: "suspend the dep-mapper LOW finding as blocking until #2162 lands or 2026-12-31, whichever is first; each affected PR keeps dep-mapper's manual trace and discloses LOW in its body; the suspension lands via a PR I approve." Implemented by #2214. Conditions enforced: dep-mapper still runs; a valid manual trace at .claudetmp/oversight/step{N}-dep-mapper-trace.md; the PR body carries the "dep-mapper LOW disclosure (suspended blocker)" section; never applies on CRITICAL or human_gate_required steps.
reason_category: OTHER

---

## Currently suspended

SUSPENDED: dep-mapper expires: 2026-12-31 until-closed: #2162

---

## Re-enable log

| Gate / Reviewer | Re-enabled | Notes | Authorized by |
|---|---|---|---|
| *(none yet)* | | | |
