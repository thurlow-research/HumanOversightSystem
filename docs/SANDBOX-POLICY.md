# SANDBOX-POLICY

Reference documentation for `contract/sandbox-policy.template.json` — the HOS
sandbox and permission policy.

**Status:** the template is a *faithful, path-templated copy of the Human-role
profile proven in production*, reconciled against the live config as of
2026-08-02 (#1185). It is checked in so the policy is source-controlled and
reviewable rather than living only in one operator's untracked
`.claude/settings.local.json`. As of #1221, the template is **generatable for
`human`** via `scripts/framework/gen_sandbox_config.py`, and `hos_install.sh`
runs that generation at install time (never overwriting a pre-existing file).
`generate` writes `.claude/settings.local.json` **only into a clone that has
no existing policy file** — an existing, parseable file is always left
untouched, never overwritten (2026-08-15 human ruling; there is no
`--force`). A hand-maintained clone (an existing file with no values sidecar
yet) gets *enrolled* on the next `generate` run: only the
`.claude/hos-sandbox.values` sidecar is written, adopting the existing file
as baseline — `settings.local.json` itself is still never touched
(2026-08-16 ruling). `bin/hos-human`'s preflight (`--role human`) warns,
non-blocking, on stderr when a clone's live file has since diverged from a
fresh generation, but now **hard-blocks session start when the policy is
missing entirely** (no sidecar / not enrolled) — E-2 resolved 2026-08-16;
divergence stays a warning. **It is not yet applied to `worker` or
`overseer`** — both currently run under `bypassPermissions` and don't opt
into this check; extending it is v0.7.0 work, tracked at **#1146**.
Reconciliation is not automatic — see §4 item 7 for what still needs
re-checking by hand after any further live edit.

---

## 1. Why this is in the repo at all

Until now the sandbox policy existed exactly once: in a gitignored
`.claude/settings.local.json` on a single machine. That has every failure
property this repo has documented elsewhere:

- **Not reviewable.** A security boundary that no reviewer ever sees is not a
  reviewed boundary. It drifts by hand-editing, with no diff and no history.
- **Not reproducible.** A fresh clone, a new machine, or a rebuilt role account
  produces a session with *no* sandbox — silently, and with no error, because an
  absent policy is indistinguishable from a permissive one.
- **Not enforceable.** Nothing checks that a role is running under the policy it
  is supposed to be running under.

This mirrors `research/findings/unenforceable-rules-need-verification-mechanisms.md`
("a rule with no checkable artifact is merely advisory") and
`convergence-ledger-must-persist.md` (state a gate's behavior depends on cannot
be per-machine). Committing the policy is the first step; installing and
verifying it are #1146.

---

## 2. Current reality this policy does *not* yet describe

Verified on 2026-08-01, and stated plainly because the gap matters:

| Path | Launcher | Permission posture |
|---|---|---|
| Interactive worker | `bin/hos-worker:23` | `claude --dangerously-skip-permissions` |
| Interactive overseer | `bin/hos-overseer:19` | `claude --dangerously-skip-permissions` |
| Autonomous cron (both) | `bin/hos-cron` | `--permission-mode bypassPermissions` |

Neither `Worker/.claude/settings.json` nor `Overseer/.claude/settings.json`
contains any `sandbox` key. **The autonomous roles run today with no sandbox and
no permission gate.** The safety net is entirely the GitHub App's scoped
permissions plus the overseer's merge guardrails — as `bin/hos-cron:851-856`
states explicitly.

One consequence worth recording: `CLAUDE.md`'s "Shell usage" section justifies
its rule by saying an unallowlistable command "will hang with nobody to answer"
on Worker/Overseer. Under `bypassPermissions` that cannot happen — nothing
prompts. The rule is still good practice (auditability, reuse, testability), but
its stated rationale describes a hazard that only becomes real *once this policy
is actually applied to those roles*. It is written in the future tense of a
sandbox that is not yet deployed.

---

## 3. What each block does

### `sandbox.enabled` + `failIfUnavailable`
`enabled: true` turns on OS-level isolation. `failIfUnavailable: true` makes a
sandbox that cannot start a **hard startup failure** rather than a warning
followed by an unsandboxed run. This is the fail-closed choice: a role that
cannot be isolated must not run at all. Without it, a missing `bwrap` on a
rebuilt machine silently downgrades to full host access.

### `allowUnsandboxedCommands: false`
Makes the `dangerouslyDisableSandbox` escape hatch inert — the parameter is
ignored entirely rather than merely prompted for. The `ask` rule on
`Bash(dangerouslyDisableSandbox:true)` is belt-and-braces; with
`allowUnsandboxedCommands: false` the escape is already closed.

### `disableBypassPermissionsMode: "disable"`
Blocks `--permission-mode bypassPermissions`. **This directly conflicts with how
`bin/hos-cron` launches today** (§2). Reconciling the two is the core of the
#1146 design: either cron stops using `bypassPermissions`, or this key cannot be
applied to those roles. It cannot be both.

### `autoAllowBashIfSandboxed: true`
Inside the sandbox, bash commands are not individually prompted — the filesystem
and network boundaries are doing the containment, so a second per-command
approval gate adds friction without adding control. This is what makes an
allowlist-plus-sandbox posture usable without a human present. It is also why
the `permissions.allow` list below is about *intent and auditability* more than
about hard enforcement.

### `defaultMode: "auto"`
Routes decisions through the auto-mode classifier rather than prompting or
blanket-allowing.

### `permissions.deny`
Denies are evaluated ahead of allows and produce an immediate refusal, never a
prompt. The list covers four families:
- **Secrets** — `.env*`, `~/.ssh/**`, and every App private key (`*.pem`). Note
  a role may still *read its own* key via `sandbox.filesystem.allowRead`
  (`__CONFIG_DIR__/__ROLE__.pem`); the `permissions.deny` entries stop the agent
  from reading them as file content through the tool layer.
- **Self-modification** — `.claude/settings.json`, `.claude/settings.local.json`,
  `.claude/hooks/**`, `.envrc`, `bin/**`. An agent must not edit the policy that
  constrains it, or the launcher that sets its permission mode (`bin/hos-worker`,
  `bin/hos-overseer`, `bin/hos-cron`) — see the escalation chain documented in
  #1183. **Open question (§4):** `.claude/agents/**` is *not* denied, so agent
  definitions remain editable.
- **Interactive/pager/process-control commands** — `vi`, `less`, `top`, `watch`,
  `kill`, `systemctl`, `sudo`, … These block indefinitely waiting for a TTY that
  an autonomous session does not have. Denying them converts a hang into an
  immediate error, which is the single most important property for unattended
  operation.
- **Irreversible git/GitHub operations** — force-push in its three spellings,
  `gh auth token` (leaks a live token into the transcript), `gh secret`,
  `gh repo delete`.

### `sandbox.filesystem`
`denyRead: ["__HOME__/"]` denies the home directory wholesale, then `allowRead`
re-opens the specific subtrees actually needed (tool caches, vendor CLI config,
the role's own Claude project state). Deny-then-selectively-allow is the correct
direction: a new dotfile appearing in `$HOME` is unreadable by default rather
than readable by default.

`allowWrite` is deliberately *narrower* than `allowRead`.

`denyWrite` closes the gap the `permissions.deny` `Edit(./bin/**)` entry above
leaves open: `Edit(./bin/**)` blocks only the Edit *tool*, not a Bash-level write
(`sed -i`, `cp`, `mv`, `tee`, a `>` redirect) inside the sandboxed filesystem,
because `allowWrite` covers the whole project tree. `denyWrite` is enforced by
the OS-level sandbox itself, so it applies regardless of which tool or command
performs the write. `denyWrite: ["__PROJECT_ROOT__/bin"]` makes the launcher
directory unwritable by any means, closing the third link of the escalation
chain documented in #1183 for real rather than at the tool-permission layer
only. (`denyWrite` is a supported sibling of `denyRead`/`allowRead`/`allowWrite`
in the filesystem sandbox schema — confirmed present in the Claude Code binary,
resolving the "unverified, needs checking" flagged in #1185.)

`denyWrite` also carries a second entry,
`"__PROJECT_ROOT__/.claude/hos-sandbox.values"`, for the same reason: the
`permissions.deny` `Edit(...)` denies on the `hos-sandbox.values` sidecar
(#1221) stop only the Edit tool, and a Bash-level write is still allowlisted
and would otherwise be able to poison the sidecar `--check` reads back for
reproducibility. This closes that gap at the OS layer, matching `bin/**`'s
treatment above.

### Arbitrary code execution is intentional, not an oversight

`permissions.allow` grants `Bash(python3 *)`, `Bash(node *)`, `Bash(curl *)`,
`Bash(bash scripts/*)`, and similar — on their face, unrestricted code
execution. A future audit will flag this. It is deliberate: **the OS-level
sandbox (`sandbox.filesystem` + `sandbox.network`) is the actual security
boundary; the `permissions` layer is friction management for an autonomous
session, not a containment mechanism.** With `autoAllowBashIfSandboxed: true`,
that friction is mostly turned off anyway — the allowlist's value is intent and
auditability (what commands does the role's config expect to run), not
enforcement. Do not "fix" this by narrowing the allowlist; narrow
`sandbox.filesystem`/`sandbox.network` instead if a role needs less capability.

### `sandbox.network.allowedDomains`
Egress allowlist. Four groups: GitHub, the three model vendors (Anthropic,
OpenAI, Google — needed because the cross-vendor panel shells out to `codex` and
`agy`), package registries (PyPI, npm), and Playwright's browser CDNs. Anything
not listed is refused.

Per the Claude Code settings schema, `network.strictAllowlist` makes non-listed
hosts **deny deterministically instead of prompting**. It is *not* set in this
template — see §4.

---

## 4. Open questions for the #1146 design chain

These are deliberately unresolved here. This document records the Human profile
as it exists; it does not pre-empt the design.

1. **Per-role variance.** This template encodes the Human profile, in which
   Human is a read-only observer of Worker and Overseer (`Read(...)` on both,
   `Edit(...)` denied on both). Worker and Overseer cannot simply inherit it:
   each needs write access to its own clone, and neither obviously should retain
   read access to the others'. The per-role matrix is unresolved.

2. **`disableBypassPermissionsMode` vs. `bin/hos-cron`.** Direct contradiction
   (§3). Must be settled before this policy can be applied to the autonomous
   roles.

3. **`strictAllowlist` and deny-instead-of-prompt generally.** `REQUIREMENTS-034`
   §1 assumes an unmatched command *prompts* and therefore hangs, and builds a
   detection layer around that. But prompting is configurable: `strictAllowlist`
   already does deny-instead-of-prompt for network, and a `PreToolUse` hook
   returning `permissionDecision: "deny"` generalises it to any tool call. That
   converts an indefinite hang into an immediate, actionable error. This is not
   the `REQUIREMENTS-034` §4 non-goal "auto-approving prompts" — it is
   auto-*denying*. Whether HOS adopts it changes how much of the hang-detection
   layer is load-bearing.

4. **`.claude/agents/**` editability.** Denied are `settings*.json` and
   `hooks/**`, but not `agents/**`. Agent definitions are a governance surface;
   whether an agent may rewrite them warrants an explicit ruling rather than
   falling out of a glob.

5. ~~**`Edit(./bin/**)`.**~~ **Resolved (#1183, #1185).** Re-added to
   `permissions.deny`, and backed by a matching `sandbox.filesystem.denyWrite`
   entry so a Bash-level write (not just the Edit tool) is also blocked — see
   §3. The live Human profile had already re-added the `Edit(...)` half by hand
   on 2026-08-02; this template now matches, plus closes the Bash-write gap
   the hand-edit didn't cover.

6. ~~**Placeholder substitution must fail closed.**~~ **Discharged (#1221,
   AD-3).** `scripts/framework/gen_sandbox_config.py` hard-fails (exit 5) on
   any surviving `__NAME__` in the serialized output *before* any filesystem
   write of any kind — no partial file is ever written. Every `__NAME__` must
   still be substituted at generation time; the generator now enforces this
   mechanically rather than relying on install-time discipline.

7. **Live-vs-template reconciliation is not fully closed.** Comparing this
   template (placeholders substituted) against the live, hand-edited
   `Human/.claude/settings.local.json` on 2026-08-02 surfaced two items this PR
   deliberately does *not* resolve, because each needs a call this document
   shouldn't make unilaterally:
   - `Bash(claude *)` is allowed live but not in this template. Unclear whether
     nested-Claude invocation should be a Human-only allowance or belong in the
     shared template for all roles (an autonomous role invoking `claude` on
     itself is a different risk shape than an interactive one doing so).
     **#1221** confirms this stays live-only: `permissions.allow` is never
     edited by the generator or its template reconciliation (an allow is not
     monotonic — importing a live-only allow grants capability no reviewer
     approved).
   - The live config's absolute-path `Read(...)`/`Edit(...)`/`Write(...)` entries
     are consistently double-slash (e.g. `Read(//home/scott/.../Worker/**)`),
     while this template's placeholder substitution (`__HOS_ROOT__/Worker/**` →
     a single leading slash) produces single-slash paths. Whether Claude Code's
     permission-glob matcher treats these differently is **unverified** — flag
     for the #1146 design chain rather than guess at security-relevant glob
     semantics. **#1221's** template reconciliation deliberately emits three
     `bin/**` and six force-push deny spellings (relative, single-slash
     absolute, double-slash absolute; see §3 above) *because* this item is
     unresolved — the redundancy costs zero capability and may be pruned once
     #1146 verifies the matcher.
   - **New, routed to #1146:** `Edit(./.claude/settings.json)` and
     `Edit(./.claude/settings.local.json)` carry the same latent
     single-spelling gap as the pre-#1221 `bin/**` entry did, but #1221's
     template reconciliation deliberately does not widen them — that is
     outside its stated remit (the §5/#1221 reconciliation plus the new
     `.claude/hos-sandbox.values` entries it introduces), not an oversight.

---

## 5. Placeholders

`scripts/framework/gen_sandbox_config.py` (#1221) is the generator that
substitutes these. Third column per its §3.2 flag table.

| Placeholder | Meaning | Generator flag / default |
|---|---|---|
| `__HOS_ROOT__` | Parent directory holding the per-role clones | `--hos-root`, derived: `--clone-dir`'s parent |
| `__PROJECT_ROOT__` | This role's own clone | `--project-root`, derived: `realpath(--clone-dir)` |
| `__CONFIG_DIR__` | HOS config dir (`apps.env`, App private keys) | `--config-dir`, derived: `${HOS_CONFIG_DIR:-$HOME/.config/hos}` |
| `__HANDOFF_DIR__` | This role's handoff directory | `--handoff-dir`, **required-explicit — no default** |
| `__HOME__` | The service account's home directory | `--home`, derived: `$HOME` |
| `__ROLE__` | `human` \| `worker` \| `overseer` | `--role` (no separate flag of its own); only `human` is generatable — `worker`/`overseer` fail closed naming #1146 |
| `__CLAUDE_PROJECT_STATE__` | Claude Code's per-project state dir for this clone | `--claude-project-state`, **required-explicit — no default** |

---

## 6. Related

- **#1146** — sandbox worker + overseer (hang detection, durable recording,
  next-run behavior change); `docs/v0.6.0/REQUIREMENTS-034-sandbox-hang-detection.md`
- **#1053** — run HOS processes in sandboxes
- **#1114** — unfilled `__CLONE_ROOT__` placeholder not caught before session start
- **#957** — per-role checkouts drift across releases
- **#1183** — Human-clone beta: bypassPermissions escalation chain + unmeasured
  keystone control (`allowUnsandboxedCommands: false`)
- **#1185** — this template had drifted from the live-validated Human profile;
  source of this PR's reconciliation
- `CLAUDE.md` — "Shell usage under the sandbox"
