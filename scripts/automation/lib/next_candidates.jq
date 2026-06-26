# next_candidates.jq — canonical work-selection ordering for the HOS worker (#901).
#
# Input:  the GitHub "list issues" API response (a JSON array), as returned by
#         issues?state=open&milestone=<N>&labels=needs-ai.
# Output: one "#<number> [<priority>] <title>" line per ELIGIBLE issue, ordered
#         highest-priority first, then lowest issue number.
#
# Eligibility: open needs-ai issues that are NOT also labelled needs-human.
# Priority:    priority:critical > priority:high > priority:medium > priority:low.
#              An issue with no priority:* label defaults to "low" (rank 3) so the
#              existing backlog needs no backfill.
# Tie-break:   ascending issue number (preserves FIFO-within-band behaviour).
#
# SINGLE SOURCE OF TRUTH. Both worker selection paths must use this exact filter:
#   (a) bin/hos-cron  _build_context  → --jq "$(cat .../next_candidates.jq)"
#   (b) bootstrap/worker-cron-prompt.md Step-2 fallback (inlined; kept identical,
#       verified by tests/automation/test_next_candidates.py).
# If the two diverge, the worker picks different work depending on whether the
# pre-computed context block is present. Keep them in lock-step.

[ .[]
  | select((.labels // []) | map(.name) | index("needs-human") | not)
  | { number, title, names: ((.labels // []) | map(.name)) }
  | .rank =
      ( if   (.names | index("priority:critical")) then 0
        elif (.names | index("priority:high"))     then 1
        elif (.names | index("priority:medium"))   then 2
        else 3 end )
  | .priority = (.rank as $r | ["critical", "high", "medium", "low"][$r])
]
| sort_by(.rank, .number)
| .[]
| "#\(.number) [\(.priority)] \(.title // "")"
