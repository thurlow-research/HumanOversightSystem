Title: Reviewer Subagents Must Return Findings in Response Text, Not Just Write to Disk
Role: oversight-mechanism — reliability of agent orchestration
Finding: When reviewer subagents write findings only to disk files and return a one-line summary, the orchestrating agent must issue a separate Read call to retrieve the findings. This breaks the clean agent→orchestrator contract (the caller gets findings from the return value, not from a side-effect read), adds latency, and creates a failure mode where the orchestrator proceeds without reading the disk file. The fix: reviewer agents write the audit-trail file AND return full findings in response text. Both records must be consistent.
Evidence: CPS overnight run 2026-06-16, issue #327.
Implications: Any agent that writes state as a side effect must also return that state in its response. The response is the primary return channel; disk writes are the audit trail.
Related: the-recorder-must-not-be-in-the-recorded-set.md
