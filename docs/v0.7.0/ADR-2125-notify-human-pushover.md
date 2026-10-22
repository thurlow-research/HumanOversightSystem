# ADR-2125: A direct Pushover "help" channel. A thin `bootstrap/notify_human.sh` over one stdlib Python module, credentials parsed in-process and never in an argument list, a per-key locked dedup record under `~/.hos/notify/`, a hard 25 s wall bound, and test overrides that cannot point real credentials anywhere but Pushover

**Status:** ACCEPTED FOR DESIGN. AD-1 to AD-13 bind `technical-design` for **S1**, which is designed on ESC-1 (B) (see §8). AD-14 sets direction for S2 and S3 and binds their TDs once ESC-2, ESC-3 and ESC-4 are ruled.
**Date:** 2026-10-22
**Author:** architect (autonomous worker cycle; no human present). This ADR records the human's 2026-10-20 rulings on #2125 and does not originate any of them.
**Issue:** #2125 · **Milestone:** v0.7.0 · **Risk tier: HIGH.** The feature adds a new egress path to a third party, a new credential, and new calls on `bin/hos-cron`'s pre-auth path. Every slice lands on protected surface: `bootstrap/**` and `bin/**` (`scripts/framework/protected_surfaces.txt`), and S1 also touches `CLAUDE.md`. The human gate applies at merge, whatever tier is computed.
**Inputs:** `docs/v0.7.0/REQUIREMENTS-2125-notify-human-pushover.md` (pm-agent, `5206c393a`; VF-1 to VF-7, REQ-1 to REQ-19, AC-1 to AC-17, ESC-1 to ESC-4). Issue #2125 body and both comments, read as data: the human's credential ruling of 2026-10-20 and the worker's cross-issue annotation of 2026-10-22. ADR-2100 AD-9, AD-11 and AM-9. ADR-1605 AD-18, AD-19 and AD-20. REQUIREMENTS-1605 AC-39 and AC-40. TECHNICAL-DESIGN-1605 §15.7 and §15.8 (the as-designed call sites). ADR-1944 Amendment 6 (D17c, A6-3, A6-4). Code read: `bin/hos-cron:163-370, 455-490, 940-1016`, `bin/lib/usage_pause.py` (`_home`, `_create_fresh`, `write_atomic`, `_state_dir`), `bootstrap/lib/hos_tmp_root.py` (`_home`, `_require_private_dir`, `read_registry`, `register`), `scripts/automation/lib/cycle_log.py`, `scripts/oversight/lib/audit_log.py`, `scripts/automation/lib/merge_config.py:114-150`, `scripts/automation/lib/github.py`, `bootstrap/get_app_token.sh:140-195`, `scripts/framework/framework_consumer_files.txt`.
**Consumers:** `technical-design` → `coder` → review chain. On S1, `security-reviewer` is mandatory (credential handling, transport, the AD-7 override rule), and so are `privacy-reviewer` (third-party payload, AD-9), `reliability-reviewer` (AD-6, AD-8) and `ops-reviewer` (the `human-notified` event, AD-11). On S2 and S3, `reliability-reviewer` is mandatory.
**Does NOT re-litigate:** the credential location, file format, `--test` and the unsandboxed caller (human, 2026-10-20). The rule that the channel must not depend on the monitoring stack (human, 2026-10-20). The 6 h window and `~/.hos/notify/` (issue). ADR-2100's alert step, its 12 h state TTL and its interim filer. ADR-1605's hold, its 1 h throttle and its `check_error` path. ADR-1944's Grafana route. Where the requirements and those merged ADRs differ, **the merged ADRs win**. I found no such conflict that changes a caller's contract (§7).

---

## 0. Verification findings (working tree at `5206c393a`)

### 0.1 Confirming pm-agent

- **VF-1 CONFIRMED.** Neither the code nor `docs/CRON-SETUP.md` contains `notify_human` or `pushover`. The only references are design prose, in ADR-1605, ADR-2100, TD-1605, REQUIREMENTS-1605 and ADR-1944.
- **VF-2 CONFIRMED.** `bin/hos-cron:253` sets `_HOS_DIR="${HOS_STATE_DIR:-${HOME}/.hos}"`. The Python equivalent already exists as `bin/lib/usage_pause.py:1559-1560` (`_state_dir`).
- **VF-3 CONFIRMED.** `~/.config/hos/` holds `projects.conf` (`:178`) and `claude-auth.env` (`:1000`). Note that `claude-auth.env` is **sourced** (`:1007-1009`). `pushover.env` must not copy that pattern (AD-4).
- **VF-4 CONFIRMED** for the line numbers S2 depends on. The auth block is `:955-962`, the lock reclaim is `:316-334`, and the usage gate is `:461-484`.
- **VF-7 holds in substance.** `HOS_CYCLE_ID` (`:356`) embeds `_project_safe`, but the value cannot be parsed back reliably, because a project key may itself contain `-`. AD-10 adds the variable.

### 0.2 Architect findings (these shape the design)

- **AF-1 (HIGH, design-shaping): the repo's only HTTP-with-a-secret pattern puts the secret in argv.** `bootstrap/get_app_token.sh:143-193` passes `-H "Authorization: Bearer ${JWT}"` on curl's command line, so the JWT is readable through `/proc/<pid>/cmdline` by any local user for the lifetime of the request. That pattern is **not** reused here (AD-5). The JWT is short-lived, so that exposure is out of this ADR's scope. It is recorded as follow-up N-1 and not filed here.
- **AF-2: no Python HTTP client exists to reuse.** A search of `scripts/automation/`, `scripts/automation/lib/`, `bin/lib/`, `bootstrap/` and `bootstrap/lib/` for `urllib.request`, `http.client` and `requests` returns nothing. `scripts/automation/lib/github.py` shells out to `gh api`, which needs GitHub auth and a GitHub host, so it is unusable here by REQ-3. The transport is therefore new code, kept as small as the stdlib allows (AD-5).
- **AF-3: the audit writer defaults the role to `worker`.** `cycle_log.log_event` builds `{"event", "role": "worker", "timestamp", **kwargs}` (`cycle_log.py:61-66`), so a caller-supplied `role=` overrides the default. The notifier must always pass `role` (AD-11). `audit_log.write_event` writes with `open("xb")` under `audit/log/`, and it uses no temp file and no `$TMPDIR`, so it works inside ADR-2100's dedicated-`TMPDIR` alert step.
- **AF-4: two "home" conventions are on `main`.** `hos_tmp_root._home()` uses the passwd home (`:136-137`), and `usage_pause._home()` uses `$HOME` (`:838-839`). AD-4 picks the passwd home for the credential and AD-8 keeps `bin/hos-cron`'s `$HOME` expression for state, and each choice is justified there.
- **AF-5: `bin/hos-cron` does not source the clone's `config.sh`.** A grep for `config.sh` finds no match. So the `HOS_*` variables a notifier sees come from the crontab, from `bin/hos-cron`'s own exports, and from callers. A committed branch cannot inject one into a cron process. That bounds the threat model behind AD-7 and R-5.
- **AF-6: the as-designed ADR-1605 call sites (TD-1605 §15.7 and §15.8) fix four facts the notifier must accept.**
  - `--since` is `YYYY-MM-DDTHH:MM:SSZ`.
  - `bin/hos-cron`'s `check_error` call passes `--url https://github.com/<slug>/actions/workflows/dependency-audit.yml`, which is a workflow URL, not a run URL.
  - The body file is written with mode 0600 into `tempfile.mkdtemp()`.
  - The result maps to `sent` or `undelivered:<absent|not-executable|exit-N|timeout>`.
  
  So exit 0 is recorded as `sent`, and AD-3's dedup exit 0 must mean "the human has been told".
- **AF-7: in `bin/hos-cron`, the lock reclaim (`:316-334`) runs before `HOS_CYCLE_ROLE` is set (`:351`) and before `_audit` is defined (`:368`).** S2's `cron-lock-stuck` call must therefore pass `--role` and `--project` explicitly (AD-14).
- **AF-8: `merge_config.resolve_repo_slug` (`:117-150`) is the canonical slug parser, but the notifier cannot import it.** It imports `scripts.automation.lib.merge_authority`, a package import that `python3 -I` cannot resolve without adding the clone to `sys.path`. Its `subprocess.run` also has no timeout. AD-9 keeps its rules and pins parity with a test.
- **AF-9: two existing safe-file patterns to reuse as patterns.** `hos_tmp_root.register` (`:388-441`) takes an `flock` on an `O_NOFOLLOW` lock file and writes the registry atomically. `usage_pause._create_fresh` and `usage_pause.write_atomic` (`:388-397`, `:935-967`) create files with `O_EXCL|O_NOFOLLOW` and rename them into place. AD-8 follows both. It does not import them (AD-1 says why).

---

## 1. Organizing principle

The notifier is a **dumb, bounded, GitHub-free pipe with exactly one piece of memory**, its dedup record. Detectors decide **whether** to call it (REQ-14). The notifier decides only **whether this key was already sent**, and then **delivers or fails, in under 25 s, without leaking the credential**. Every failure is a non-zero exit with a fixed reason token. The caller owns what that failure means, and every designed caller treats it as `undelivered` and carries on. When the notifier has to choose between staying quiet and sending, it **sends**: a duplicate push is a nuisance, but a missing one is the outage this issue exists to prevent.

---

## 2. Decisions

### AD-1: Shape. A thin bash entry point over one stdlib-only Python module, run with `python3 -I`. (BINDING; REQ-1, REQ-3, REQ-5, the v0.7.4 shell-to-Python theme.)

- `bootstrap/notify_human.sh` is the **fixed path** that ADR-1605 AD-20, TD-1605 §15.7 and ADR-2100 AD-9 call. It does three things only:
  1. It resolves its own directory with `cd -P`.
  2. It checks that `python3` is on `PATH`. If it is not, it prints the AD-3 stdout line with `reason=no-python` and exits 4.
  3. It runs `exec python3 -I "<dir>/lib/notify_human.py" "$@"`.
  
  It reads no credential, no state and no environment value, and has no `set -x`. It follows `bootstrap/setup_clis.sh` style (`set -euo pipefail`, colour only when stderr is a TTY).
- `bootstrap/lib/notify_human.py` holds **all** of the decision logic: argument grammar, the cause table, credential parsing, the dedup record, transport, rendering and the audit call. It uses the **stdlib only** and supports Python 3.10 or later (the `hos_bootstrap.sh` floor). It is invoked by file path under `-I`, the same as `usage_pause.py` (`bin/hos-cron:461`). `-I` ignores `PYTHON*` variables and the user site directory, and keeps the script directory and the working directory off `sys.path`.
- **Why Python.** Every part of the job is decision logic or secret handling: closed-set validation, a credential file that must be parsed without being sourced, `fstat` ownership and mode checks, an `flock`-guarded record with an untrusted-state rule, TLS with verification, a bounded JSON response parse, and a hard wall-clock deadline. In bash, the credential would live in shell variables. Any `curl` invocation would be one flag away from AF-1, and the locking and parsing would be the hand-rolled shell logic that v0.7.4 is moving away from.
- **Why `bootstrap/lib/` and not `scripts/automation/lib/`.** The notifier must run under `-I` from a fixed bootstrap path, before auth, with no package import path. `bootstrap/lib/hos_tmp_root.py` is the precedent for a bootstrap-side stdlib module.
- **Why the AF-9 helpers are not imported.** `hos_tmp_root` is the tmp-root trust guard. Importing its private `_require_private_dir` would couple the notifier's semantics to a security module that changes for unrelated reasons. `usage_pause` is a 2,000-line module in `bin/lib/`. The checks needed here are about ten lines each. The TD names, at each use site, which existing function its check mirrors. That keeps the duplication declared (D41) without introducing a cross-module import.
- **Rejected alternatives:**
  - **(a) A pure bash script with `curl`.** Even with `--data @-` keeping the token out of argv, the token would still sit in shell variables, and the parsing and locking would still be shell decision logic.
  - **(b) Python that shells out to `curl`.** That adds a child process whose argv and environment are one mistake away from AF-1.
  - **(c) `requests`.** It is not stdlib, and the notifier must run before any venv is guaranteed.
  - **(d) A `-m scripts.automation...` module.** A package import cannot be resolved under `-I` from an arbitrary working directory.

### AD-2: The interface. A closed argument grammar and one cause table. (BINDING; REQ-1, REQ-2, REQ-11. ADR-1605 AC-40 and ADR-2100 AD-9 shapes accepted unchanged.)

- **Call shape:** `notify_human.sh --cause <id> (--issue <n> | --issue none | --url <u>) --since <iso> [--priority high|normal] [--body-file <path>] [--role <r>] [--project <p>]`. Separately, `notify_human.sh --test`, which takes no other argument.
- **The grammar is strict.** Each flag may appear at most once. An unknown flag, a missing value, a repeated flag, a positional argument, or `--test` combined with anything else is a usage error (exit 2).
  - `--issue <n>` must full-match `[1-9][0-9]{0,8}`.
  - `--since` must full-match `[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z` (AF-6) **and** parse as a real UTC datetime.
  - `--url` must full-match `https://github\.com/[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+`, with at most 512 bytes. It must contain no `..` segment, no query, no fragment and no percent-encoding. Both ADR-1605 URL forms pass (AF-6). Everything else is rejected.
- **The cause table is a single module-level mapping** `CAUSES = {cause: priority}`, holding exactly the nine causes and priorities of REQ-2. Membership is the only check. `test` is not in the table. `--priority`, when given, must equal the table value, or the call is exit 2.
- **`--body-file`, under ESC-1 (B):** the flag is accepted and its value must be non-empty. **The file is never opened, read or checked for existence.** The notifier transmits nothing from it. This is a deliberate departure from REQ-4's "an unreadable `--body-file` is a usage error" (AM-1). If a non-zero exit came from an argument the notifier ignores, a caller whose temp body file could not be written would lose its push. That is silence caused by an unused input. Under ESC-1 (A), the file is read with a bounded, `O_NOFOLLOW` read of the first line only, and a failed read **degrades** to sending the push without the extra line. It never becomes an exit 2.
- **`--role` and `--project`** are optional and are never rejected for their charset (ADR-2100 AD-9 requires the call to be made even for a bad project key). Resolution is defined in AD-10, and rendering in AD-9.

### AD-3: Exit codes, one stdout line, and a fixed reason vocabulary. (BINDING; REQ-4. This is an interface pinned for every caller.)

- **Exit codes:**
  - **0**: `sent`, `deduped` or `test-sent`.
  - **2**: usage error, or an unpaired or invalid test override (AD-7).
  - **3**: credentials unavailable.
  - **4**: delivery failed. This includes a missing `python3`, a lock timeout and an internal error.
  
  No other code is used. Under ADR-1605's mapping (AF-6), a non-zero exit is recorded as `undelivered:exit-<N>`, so 2, 3 and 4 reach that caller's log line unchanged.
- **The stdout line.** On every exit, stdout carries **exactly one** ASCII line, matching:
  `^NOTIFY outcome=(sent|deduped|test-sent|failed) cause=([a-z][a-z-]{0,31}|test|-)( reason=[a-z][a-z-]{0,31})?$`
  `reason` is present if and only if `outcome=failed`. `cause=-` is used only when the call fails before the cause is validated. Nothing else is written to stdout. The human-readable detail goes to stderr, prefixed `notify_human:`. Any caller-supplied value echoed there goes through the AD-9 renderer first.
- **The reason vocabulary is closed.** The TD may add a token only by amending this list.

  | Exit | Tokens |
  |---|---|
  | 2 | `usage`, `test-override` |
  | 3 | `credentials-missing`, `credentials-insecure`, `credentials-malformed` |
  | 4 | `network`, `tls`, `http-4xx`, `http-5xx`, `redirect`, `rejected` (a 2xx response whose `status` is not 1, or a body that does not parse), `timeout`, `lock-timeout`, `no-python`, `internal` |

- **Internal errors.** A top-level handler turns any unexpected exception into `reason=internal`, exit 4, and logs **only the exception class name** to stderr. It never logs the message or the traceback, because transport exceptions can embed request data. A static test pins that the module never calls `traceback.print_*` and never formats an exception object into output.

### AD-4: Credentials. The human's ruling, made mechanical. (BINDING; REQ-5. The location and format are the human's, 2026-10-20.)

- **Path.** `<passwd home>/.config/hos/pushover.env`, where the home is `pwd.getpwuid(os.getuid()).pw_dir`, as in `hos_tmp_root._home()`. It is **not** `$HOME`, and `XDG_CONFIG_HOME` is not consulted. The credential is the one input whose location a caller's environment should not be able to move. Every caller passes `HOME` (AD-20's allowlist), but a redirected `HOME` would let an environment writer route the human's pushes to a different Pushover account, which silently suppresses them. In normal cron use, the passwd home and `$HOME` are the same directory. The only redirect is the paired test override (AD-7).
- **Open and verify.** The file is opened with `O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC`, then checked with `fstat` on the descriptor: it must be a regular file, owned by `os.getuid()`, with `mode & 0o077 == 0`, and no larger than 4096 bytes. A symlink (`ELOOP`) or a failed check gives `credentials-insecure` and exit 3. The stderr line gives the `chmod 600` and `chown` remedy and never shows the content. A missing file (`ENOENT`) gives `credentials-missing`.
- **Parse, never source.** The content must be strict UTF-8 that is all ASCII. A trailing `\r` is stripped from each line. Blank lines and lines whose first non-space character is `#` are ignored. Every other line must full-match `(PUSHOVER_TOKEN|PUSHOVER_USER)=("[A-Za-z0-9]{1,64}"|'[A-Za-z0-9]{1,64}'|[A-Za-z0-9]{1,64})`. One pair of matching quotes is tolerated because the human's ruling says "shell `KEY=value` lines". The following give `credentials-malformed`: any other key, a duplicate key, a missing key, an `export` prefix, and a value outside the charset. The message names the line number and the key, never the value. The charset check also guarantees that a value can carry nothing into the form body except itself.
- **Lifetime.** The two values live only in local variables of the send function. They are never placed in `os.environ`, never passed to `subprocess`, never stored on an object that is logged or rendered, and never written to the dedup record or the audit event.
- **Order.** The dedup check (AD-8) runs **before** the credential read. A deduped call needs no credential, so a muted channel still reports `deduped` for keys already sent in the window. That is true: the human was told. The credential is read only when a send is about to happen, and it is read inside the AD-6 deadline.
- **Muting.** Remove or rename the file. Callers then record `undelivered:exit-3` and carry on (REQ-13). There is no other mute switch, and no `HOS_*` variable can disable the channel short of the test override.
- **Sandbox.** The file is added to no sandbox allowlist (human ruling). Only unsandboxed processes read it.

### AD-5: Transport. In-process HTTPS with verification on, nothing in argv, no proxies, no redirects, a closed field set and no retries. (BINDING; REQ-5, REQ-7, REQ-10.)

- **Endpoint.** A module constant: `PUSHOVER_ENDPOINT = "https://api.pushover.net/1/messages.json"`.
- **Client.** `urllib.request`, using `ssl.create_default_context()` with system CAs and hostname checking on. A static test pins that the module contains no `CERT_NONE`, no `check_hostname = False`, no `_create_unverified_context`, and no `subprocess` call in the send path.
- **Request.** A `POST` with a body from `urllib.parse.urlencode`, carrying a **closed field set**: `token`, `user`, `title`, `message`, `priority`. Nothing else is sent: no `retry`, `expire`, `sound`, `device`, `url` or `html`. The request also carries a fixed `User-Agent: hos-notify/1`.
- **Credential exposure.** The credentials travel only in the TLS-protected request body, built in memory. No process is spawned with them, so **AC-7's argv and child-environment property holds by construction**. The test still asserts it by recording every `subprocess` call made during a send (the only one is the AD-9 slug lookup) and checking its argv and environment.
- **Proxies are ignored.** The opener is built with `ProxyHandler({})`. AD-20's allowlist already strips `https_proxy`, so honouring it would make delivery depend on which caller ran the notifier. See ARCH-ESC-1 and R-4.
- **Redirects are refused.** A handler turns any 3xx into `reason=redirect`, so a request body is never replayed to another location.
- **Response.** At most 64 KiB is read. Then:
  - a 2xx response whose JSON object has the **integer** `status == 1` → `sent`;
  - any other 2xx → `rejected`;
  - 4xx → `http-4xx`, which includes an invalid token or user key and Pushover's 429;
  - 5xx → `http-5xx`;
  - a socket or DNS error → `network`;
  - an `ssl.SSLError` → `tls`.
  
  The response body is **never** printed or audited.
- **No retries inside a call.** The next occurrence retries, and dedup records only successes (AD-8).

### AD-6: A hard wall bound of 25 s, enforced in-process. (BINDING; REQ-7. ADR-1605 AD-20's 30 s bound and ADR-2100 AD-11's 120 s step.)

- **Total budget: 25 s,** measured on `time.monotonic()` from process start. That leaves at least 5 s of margin inside every caller's 30 s kill. Each sub-budget below is a named constant, and the TD may lower a value but not raise it:
  - lock wait: at most 5 s (AD-8);
  - slug lookup: at most 3 s (AD-9);
  - HTTP: socket timeout 15 s, further capped by the remaining budget minus 2 s, which is kept back for the record write and the audit write.
- **Why a thread.** A socket timeout bounds each socket operation, not the whole request, and a blocking `getaddrinfo` cannot be interrupted by a signal. So the HTTP call runs in a **daemon worker thread**, and the main thread waits on it with `join(remaining)`. If the deadline passes, the main thread writes the stdout line `reason=timeout`, attempts the audit write, and leaves through `os._exit(4)`. The stuck thread dies with the process, and the lock (AD-8) is released by the kernel when the process exits.
- **No dependence on the environment around the call.** There is no prompt, no TTY, and no `$TMPDIR` or `/tmp` write anywhere in the notifier. The record lives in the state directory and the credential is read into memory. The notifier therefore works inside ADR-2100's dedicated alert `TMPDIR` and under a full `/tmp`.

### AD-7: Test overrides are paired, loopback-only, and can never carry the real credential. (BINDING; REQ-10, REQ-19, AC-8, AC-17.)

- **Two variables, both test-only:**
  - `HOS_NOTIFY_TEST_ENDPOINT`. It must be `http://127.0.0.1:<port>/<path>` or `http://[::1]:<port>/<path>`. These are IP literals only. `localhost` and every other host are refused, so no DNS lookup and no remote host is possible. `http` is allowed only here.
  - `HOS_NOTIFY_TEST_CREDENTIALS`. A path to a credentials file, held to every AD-4 check.
  
  Neither name contains `TOKEN`, `SECRET`, `KEY` or `PASSWORD`, so AD-20's allowlist passes both to a caller's notifier under test.
- **Pairing.** If exactly one of the two is set, or the endpoint fails its grammar, the call exits 2 with `reason=test-override` **before** anything is read or sent. While the endpoint is overridden, the default credentials path is never opened (AC-8: the test asserts this by recording `os.open` calls).
- **The real credential cannot be smuggled in.** If the override credentials file has the same `(st_dev, st_ino)` as the default credentials path (checked by an `lstat` on the default path, which never opens it), the call exits 2 with `reason=test-override`. Combined with the loopback-only endpoint, this means **no combination of `HOS_*` variables can send the real token anywhere but `api.pushover.net`**. The only remaining case is another local user listening on a loopback port, and they would still receive only a copied file, which only the owner can make.
- **`--test` honours the overrides** (REQ-11), so AC-12 runs against the fake endpoint.
- **Session-wide test isolation (binding on S1's tests; ADR-2100 AD-10 pattern).** `tests/conftest.py` gains an autouse, session-wide fixture. It sets `HOS_NOTIFY_TEST_ENDPOINT` to a closed loopback port, sets `HOS_NOTIFY_TEST_CREDENTIALS` to a 0600 fixture file, and sets `HOS_STATE_DIR` to a per-session temp directory. As a result, **any** test that reaches the real notifier, including S2's and S3's `bin/hos-cron` tests and ADR-1605's and ADR-2100's caller tests, sends nowhere real and writes no real state. The notifier tests replace these with a live fake endpoint. A guard test asserts that the fixture is active.

### AD-8: The dedup record. One locked file per key, untrusted means absent, and only a success is recorded. (BINDING; REQ-6, AC-2, AC-3, AC-9.)

- **Directory.** The state root is `HOS_STATE_DIR` when it is set and non-empty, and `$HOME/.hos` otherwise. That is `bin/hos-cron:253`'s expression, mirrored from `usage_pause._state_dir`. The notifier uses `<state root>/notify/`. `$HOME` is kept here, unlike AD-4, so that the notifier and `bin/hos-cron` agree on one state root. `<state root>` is created with mode 0700 if it is absent. `notify/` is created with mode 0700, then checked with `lstat`: it must be a directory, not a symlink, and owned by the current user, with group and other bits stripped by `chmod` if present. A failed check makes **the directory unusable**: every call then sends, with no dedup and no record, and writes a `notify_human: WARN dedup state unusable (<class>)` line to stderr and `state=unusable` to the audit event. That errs loud (ADR-1605 AD-18).
- **The key** is the NUL-joined UTF-8 bytes (surrogate-escaped) of `(project, cause, target_kind, target, role if target_kind == "none" else "")`, where `target_kind` is `issue`, `url` or `none`. The file name is the first 32 hex characters of the key's SHA-256, plus `.rec`. Hashing makes a hostile project key path-inert. The record also stores the rendered key fields, and a record whose stored fields do not match the call's fields is treated as absent.
- **Concurrency: the lock is on the record file itself.**
  1. Open `<hash>.rec` with `O_RDWR|O_CREAT|O_NOFOLLOW|O_CLOEXEC`, mode 0600.
  2. Take `flock(LOCK_EX)`, polling with `LOCK_NB` until the AD-6 lock budget runs out. Exhausting it gives `reason=lock-timeout` and exit 4. The holder is either sending or about to record, and a caller's retry will then dedup.
  3. Once locked, re-verify that `fstat(fd)` has `st_nlink >= 1` and the same `(st_dev, st_ino)` as `lstat(path)`. If either check fails, a prune unlinked the file between steps 1 and 2. Reopen and retry, at most three times.
  4. Read the record and decide. On a send, **keep the lock held through the HTTP call**, and on success rewrite the record **in place** (`ftruncate`, `write`, `fsync`) under the same lock.
  
  Two concurrent same-key calls therefore send at most once. Different keys never contend. A torn in-place write does not parse, so it counts as absent and the next call sends (fail loud). Rename-based atomic replacement is **rejected** here because it would separate the lock from the inode that later callers open.
- **Record format.** JSON with `{"v": 1, "project", "cause", "target_kind", "target", "role", "sent_at": <int epoch>}`, at most 1 KiB, validated field by field.
- **Untrusted means absent** (ADR-2100 AD-11 rule). The record is treated as absent if it:
  - is a symlink (`ELOOP` on open);
  - is not a regular file;
  - is owned by another user, or has group or other bits set;
  - is oversized or does not parse;
  - has a missing or wrong-typed field;
  - has fields that do not match the key;
  - has `sent_at` in the future by more than 300 s, so that a forged far-future time cannot suppress the key indefinitely.
  
  If the path cannot be opened or locked because of what is there (a symlink, a foreign file, a directory), the notifier unlinks it (it owns the 0700 directory) and retries once. If that fails, it sends **without** a lock or a record, and the audit event says `state=untrusted`. The at-most-once guarantee holds only while the state is usable, which is exactly REQ-6's qualifier.
- **Decision.** If a trusted record has `now - sent_at < DEDUP_WINDOW_SECONDS` (`6 * 3600`, a named constant), the result is `deduped` and exit 0. No credential is read and nothing is sent. Otherwise the notifier sends. Only `sent` writes a record. A failure (exit 3 or exit 4) writes nothing, and `--test` neither reads nor writes records.
- **Bounded growth.** After the decision, each call prunes opportunistically. It removes up to 200 `*.rec` entries whose `mtime` is older than twice the window, taking `LOCK_EX|LOCK_NB` on each and re-verifying it before unlinking. An entry that is locked is skipped. Pruning is best-effort: its errors are ignored, and it runs only if at least 3 s of the budget remain.

### AD-9: The message. A fixed template, a locally resolved link, one renderer and named priorities. (BINDING; REQ-3, REQ-8, REQ-9. ADR-2100 AD-9's pointer-only rule, applied to every cause. ADR-1944 A6-4.)

- **Title.** The constant `HOS help`.
- **Message.** `HOS help: <cause> [<project>/<role>] — <target> — waiting since <since>`, all on one line. `<target>` is one of:
  - for `--issue <n>`: `https://github.com/<slug>/issues/<n>` (GitHub redirects that path to a PR when `<n>` is one), or `#<n>` when no slug resolves;
  - for `--url`: the validated URL, unchanged;
  - for `--issue none`: the constant `no GitHub item; see the cron log for this role`.
  
  The message never contains a path, a host name, a credential, an environment value, GitHub text, or anything from the body file (ESC-1 (B)).
- **ADR-2100 consistency.** AD-9 of ADR-2100 asks for the fixed constant "GitHub item could not be filed; see the cron log for this role" when `issue=none`. Under ESC-1 (B), the notifier supplies its own `issue=none` constant. The wording differs, but it meets the rule as written: a fixed constant with no variable detail. ADR-2100 S2 needs no change, and its body file is accepted and ignored (AD-2).
- **Slug resolution, local only.** The slug comes from `HOS_REPO_SLUG`, if set and it full-matches `merge_config._REPO_SLUG_RE` (`^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$`). Otherwise the notifier runs `git -C <clone> remote get-url origin` with `timeout=3` and a minimal environment (`PATH` and `HOME` only), and parses the result with **the same rules as `merge_config.resolve_repo_slug`**. A **parity test** runs both parsers over a fixture set of remote URLs and asserts identical results, so the copy cannot drift (AF-8, declared D41 duplication). `<clone>` is the notifier file's own repository root (`Path(__file__).resolve().parents[2]`). Any failure falls back to `#<n>` and is still sent (REQ-3).
- **One renderer** (REQ-9) for every caller-supplied value the notifier transmits or echoes, other than `--issue`, `--since` and `--url`, which are validated instead. Today that is `role` and `project`, plus the body line under ESC-1 (A). The renderer works on raw bytes:
  1. it keeps only the first line;
  2. it maps each byte outside `[A-Za-z0-9 ._,:;=()+-]` to `?`;
  3. it caps the result at 64 characters for role and project, and 200 for a body line, with `...` marking a cut.
  
  The allowlist excludes `/`, `~`, `\`, `<`, `>`, `@`, the backtick, `#`, and every control or non-ASCII byte. An empty result renders as `unknown`.
- **Priorities.** `HOS_PUSHOVER_PRIORITY_HIGH = 1` and `HOS_PUSHOVER_PRIORITY_NORMAL = 0`, which mirror ADR-1944's `hos_pushover_priority_high` and `hos_pushover_priority_normal`. If H-9 on #1944 changes them, both places change together, and the S1 PR body records that coupling. A static test pins that no priority value other than 0 and 1 is reachable, so emergency (2) is never sent.
- **Limits.** The message is at most 1024 characters by construction: the template plus 64 + 64 + 512 + 20 fixed fields comes to about 750. A test pins the worst case.

### AD-10: Role and project resolution, and one new export from `bin/hos-cron`. (BINDING; REQ-1, VF-7, AF-7. ADR-2100 AD-9 needs role and project on the push.)

- **Resolution order:**
  - role: `--role`, then `HOS_CYCLE_ROLE`, then `unknown`;
  - project: `--project`, then **`HOS_CYCLE_PROJECT`**, then `unknown`.
  
  The value is never rejected. It is rendered (AD-9) for the message and the audit event, and used raw (hashed) in the key (AD-8).
- **S1 adds one line to `bin/hos-cron`**, directly after `:365`: `HOS_CYCLE_PROJECT="$PROJECT"`, added to the same `export`. The raw key is used, not `_project_safe`, because the notifier renders it itself. This belongs in **S1**, not S2. ADR-2100 S2 and ADR-1605 Part 3 call with the AC-40 shape, which has no `--project`. Without the export, every project on the machine would render, and dedup, as `unknown`. That is a cross-project suppression bug on the very first cross-issue call. `HOS_CYCLE_PROJECT` contains none of the excluded words, so AD-20's allowlist already passes it.
- **Conflict notice.** ADR-2100 S2, ADR-1605 Part 3 and ADR-1928 S6 all edit `bin/hos-cron`. This is a one-line change beside the identity exports. Whichever change lands later rebases, and its PR body states the conflict.

### AD-11: Audit. `human-notified` through the existing writer. It never changes the exit code. (BINDING; REQ-12, AF-3.)

- **The existing writer is reused.** `scripts/automation/lib/cycle_log.py` is loaded **by file path** with `importlib`, from the notifier's own clone (`parents[2]`), which is the same technique `cycle_log` uses to load `audit_log`. The notifier calls `log_event("human-notified", ...)`. The record lands in that clone's `audit/log/`. If the file is absent (an unusual consumer layout), or the import or write raises, the notifier writes a single stderr `WARN`, and the exit code and stdout line are unchanged.
- **Fields:** `role` (always passed, AF-3), `project` (rendered), `cause` (or `test`), `target_kind`, `target` (the issue number, the validated URL, or `none`), `priority`, `outcome`, `reason` (only when `failed`), and `state` (`ok`, `unusable` or `untrusted`; present when the dedup state was not `ok`). These are the AD-3 tokens.
- **Never in the event:** a credential, the message text, body-file content or path, the credentials path, the state path, or a host name.
- **Coverage.** Every call that passes argument validation writes exactly one event, and `--test` writes one with `outcome=test-sent` or `outcome=failed`. A usage error (exit 2) writes none. It has no validated cause to record, and the caller already records `undelivered:exit-2`.
- **Timing.** The audit write happens after the stdout line is written and flushed, so a slow disk cannot turn a `sent` into a caller-side timeout.

### AD-12: Independence. No GitHub, no monitoring stack, no new caller variables. (BINDING; REQ-3, AC-10. The human's 2026-10-20 ruling.)

- The notifier makes **no** network call except the one HTTPS POST of AD-5. It reads no `GH_TOKEN` and calls neither `gh` nor `get_app_token.sh`. It contacts no monitoring host, and checks neither `hos-halt` nor suspension. Halt is the callers' job (ADR-2100 AD-11), and the human's mute is the credentials file.
- **It works in a cycle that has not authenticated.** It needs only `PATH` (for `python3` and `git`), `HOME` (for the AD-8 state root) and optional `HOS_*` names. AC-10 runs it under `env -i` plus AD-20's allowlist, with no route to GitHub.
- **Variables the notifier reads**, all documented in `docs/CRON-SETUP.md` (REQ-13):
  - `HOS_STATE_DIR`
  - `HOS_CYCLE_ROLE`
  - `HOS_CYCLE_PROJECT`
  - `HOS_REPO_SLUG`
  - `HOS_NOTIFY_TEST_ENDPOINT`
  - `HOS_NOTIFY_TEST_CREDENTIALS`
  - `HOME`
  - `PATH`
  
  Every one already passes AD-20's allowlist. **ADR-1605's "add #2125's variables by name" step therefore adds nothing**, and TD-1605 §15.7's allowlist is unchanged.

### AD-13: Shipping, registration and docs. (BINDING; REQ-13.)

- `bootstrap/notify_human.sh` and `bootstrap/lib/notify_human.py` are added to `scripts/framework/framework_consumer_files.txt`, because they ship with the consumer's `bin/hos-cron`.
- `SCRIPTS-INDEX.md` is regenerated in the same PR, with `scripts/framework/regen_all.sh`.
- The CLAUDE.md "Canonical entry points by task" table gains one row: "Sending a human a direct out-of-band push (closed cause list; cron and unsandboxed callers only)" → `bootstrap/notify_human.sh`.
- `docs/CRON-SETUP.md` gains the REQ-13 section. The credential setup is described in prose, using `install -m 600 /dev/null ~/.config/hos/pushover.env`. The keys are named, but no `NAME=value` line with a value appears (ADR-1944 A6-2, PR #1949). The section covers `--test` and its success line (`NOTIFY outcome=test-sent cause=test`), the cause and priority table, the 6 h dedup, the AD-3 exit codes and reasons with one troubleshooting row each, the AD-12 variable list, the mute rule, and the R-4 proxy limitation.
- Both new files fall under `bootstrap/**` and are protected surface, with no new entry needed. Adding a cause is a protected-surface change and needs human approval (REQ-2).

### AD-14: Trigger architecture for S2 and S3. (DIRECTION. It binds the S2 and S3 TDs once ESC-2, ESC-3 and ESC-4 are ruled. It does not bind S1.)

- **Counters live in Python, not bash.** A new `bin/lib/notify_triggers.py` holds the pure counter logic: increment, reset, threshold and the `--since` bookkeeping. Its state lives under `$_HOS_DIR/notify-trigger/<role>-<project-hash>.json`. Its I/O is injectable, it runs as `python3 -I`, and it uses the AD-8 untrusted-state checks. `bin/hos-cron` only calls it and acts on a one-line verdict.
- **Untrusted or unusable counter state is treated as "threshold reached"**, and the call is made. That errs loud, and AD-8's 6 h dedup bounds the noise to one push per key.
- **Every `bin/hos-cron` notifier call** goes through one shell helper. That helper:
  - uses `env -i` plus AD-20's allowlist;
  - applies a 30 s bound through the `_UP_BOUND` timeout-resolution idiom (`:461`), so it works without GNU `timeout`;
  - passes explicit `--role` and `--project`;
  - appends `alert=<sent|deduped|undelivered:<reason>>` to the existing log line.
  
  It never changes the cycle's exit code.
- **`cron-lock-stuck` (S2):**
  - The call is made by the process that observes `age ≥ ceiling` (`:321`), **once**, whether or not its own `mkdir` then succeeds. The "could not acquire after reclaim" branch (`:324`) is the same event seen by the same process, not a second trigger. (AM-5)
  - A dead-PID reclaim (`:331-334`) is not a trigger.
  - The call precedes `_audit` and `HOS_CYCLE_*` (AF-7), so it passes `--role "$ROLE" --project "$PROJECT"`.
  - S2's TD must state that a legitimately long cycle under a disabled cap (`HOS_CRON_MAX_SECONDS=0`, ceiling 3600 s) is now paged at high priority. That is today's reclaim, made visible, and it is disclosed rather than suppressed.
- **`token-mint-failed` and `usage-pause-fail-closed` (S2)** use the K-consecutive counter of ESC-2. The usage gate's pause path `exit 0`s at `:481`, so the call must come before that exit. `pause/limit` never counts.
- **`worker-idle` (S3a)** reads the selector's existing summary line (`select_work_candidates.py:785-795`) and does not recompute eligibility.
- **`needs-human-stale` (S3b)** reuses #1928's attention-pass computation if it is on `main` by then (REQ-17). Otherwise it reads through `scripts/automation/lib/github.py`, which provides retry, backoff and rate-limit handling, and never through hand-rolled `gh api`. A read failure means no call for that item. The "parked" test is whatever ESC-4 rules, and under (A) it calls the selector's own exclusion predicate rather than a copy.

---

## 3. Failure modes

| Condition | Behaviour | Exit / outcome | Direction |
|---|---|---|---|
| Notifier absent (before S1), or `python3` missing | Callers record `undelivered:absent`. The wrapper prints `reason=no-python` | caller-side, or 4 | Loud at the caller (AC-39) |
| Credentials file missing | stderr names the path and the setup step | 3 `credentials-missing` | Fail loud, caller continues |
| Credentials symlink, foreign owner, group or world bits, oversize | stderr gives the remedy and never the content | 3 `credentials-insecure` | Fail closed on the secret |
| Extra, duplicate or missing key, bad charset, `export` prefix | stderr names the line and key, never the value | 3 `credentials-malformed` | Fail closed |
| Unknown cause, priority mismatch, bad `--since`, `--issue` or `--url`, two targets | No read, no send, no audit | 2 `usage` | Fail loud |
| `--body-file` unreadable or nonexistent | Ignored under (B). Under (A), the push is sent without the extra line | 0 if sent | Never silent (AM-1) |
| Test endpoint without test credentials, or the reverse, or a non-loopback endpoint, or override credentials that are the real file | Nothing read, nothing sent | 2 `test-override` | Fail closed |
| DNS or connect failure | — | 4 `network` | Retry on next occurrence |
| TLS or certificate failure | — | 4 `tls` | Fail closed, never downgraded |
| Endpoint hangs or drips | The thread deadline fires at ≤ 25 s, then `os._exit` | 4 `timeout` | Bounded |
| 3xx | Not followed | 4 `redirect` | Fail closed |
| 4xx (bad token or user, 429) or 5xx | Body never printed | 4 `http-4xx` / `http-5xx` | Retry on next occurrence |
| 2xx with `status != 1`, or body unparsable | — | 4 `rejected` | Retry on next occurrence |
| State dir unusable (symlink, foreign, cannot create) | Sends with no dedup. stderr `WARN`, audit `state=unusable` | 0 `sent` | Loud (duplicates possible) |
| Record symlink, foreign, corrupt, mismatched or future-dated | Treated as absent. Replaced, or sent without a record | 0 `sent` | Loud |
| Two same-key calls at once | One sends. The other waits up to 5 s, then dedups or times out | 0 `deduped`, or 4 `lock-timeout` | At most once while state is usable (R-2) |
| Send succeeded, record write failed | Next occurrence sends again | 0 `sent` | Duplicate, not silence (R-2) |
| Caller kills at 30 s mid-send | Notifier deadline is 25 s, so this should not happen. If it does, no record is written | caller `timeout` | Duplicate possible (R-2) |
| Audit write fails, or clone not locatable | stderr `WARN` | Unchanged | Never fails the push |
| Slug unresolvable | Message carries `#<n>` | Unchanged | Degrade, never block |
| `HOS_CYCLE_PROJECT` / `HOS_CYCLE_ROLE` unset | Renders `unknown` and keys on `unknown` | Unchanged | Possible cross-project dedup only for callers outside `bin/hos-cron` (AD-10) |
| Unexpected exception | Only the class name goes to stderr | 4 `internal` | Fail loud, no leak |

---

## 4. Residuals (accepted, disclosed in the S1 PR body)

- **R-1 (security; ARCH-ESC-2): working-tree code holds the credential.** Like every bootstrap script `bin/hos-cron` runs (`get_app_token.sh` reads the App PEM, and `create_branch.sh` and `hos_repo_sync.sh` also run from the tree), the notifier runs from whatever the clone has checked out. ADR-1605 R-12 already records this for the notifier. Because the notifier now **reads the Pushover credential**, an unmerged branch that edits `bootstrap/lib/notify_human.py` and is checked out when a cron cycle calls it could exfiltrate the token. This is the same class, with a lower-value secret than the App PEM (it can send pushes to the human, and it exposes the user key). The mitigations are that the branch must be checked out in an unsandboxed cron clone, and that `bootstrap/**` is protected at merge. Hardening, as a recommended follow-up and not part of S1: run the notifier from ADR-1605's `git archive origin/main` extraction (`_BH_CODE_PATHS`), as TD-1605 §15.8 already proposes as optional.
- **R-2 (reliability): at-most-once is not exactly-once.** A duplicate push is possible:
  - after a delivery the server accepted but the notifier timed out on;
  - after a send whose record write failed;
  - when the state is untrusted or unusable.
  
  Separately, a contention loser that times out on the lock reports `undelivered` to its caller even though the winner delivered. Every one of these leans toward too many pushes, not too few.
- **R-3 (product, literal rule): dedup is per (project, cause, target), not per fingerprint.** If an ADR-1605 G-4 re-alert or a fingerprint change keeps the same cause and tracking issue within 6 h, it is deduped. ADR-1605 records it as `sent` (exit 0), and the detail is on the GitHub item. That is the issue's literal "one push per `cause+issue` per 6 h", and AC-40 assigns dedup to #2125. A **different** cause, or a new tracking issue (ADR-2100 files a new item per fingerprint), is a new key.
- **R-4 (operational; ARCH-ESC-1): no proxy support.** A host that can reach `api.pushover.net` only through an HTTP proxy cannot use the channel. `--test` reveals that at setup time, as `reason=network`.
- **R-5 (security, same class as ADR-2100 AD-11): suppression by environment control.** A writer who can set `HOS_STATE_DIR` in an unsandboxed cron process's environment can plant "sent" records and suppress pushes. A forged future `sent_at` is refused, but fresh forgeries can be planted continuously. AF-5 shows that a branch cannot do this, so the writer must already control the crontab or the caller. AD-4's passwd-home rule removes the equivalent route for the credential.
- **R-6 (privacy, human-ruled channel): a third party holds the message text.** That text is the cause, project, role, the issue URL (which includes the repo slug, even for a private repo), and `--since`. Pushover keeps it under its own retention policy. The human ruled both the channel and the template, which carries the issue URL. AD-9 keeps everything else out.
- **R-7: until S2 and S3 merge, nothing in #2125 calls the notifier except `--test`.** Its value arrives with S2, S3 and the cross-issue callers (ADR-2100 S2, ADR-1605 Part 3, #2123).

---

## 5. Slices (each at most 15 files including tests; each independently mergeable; all human-gated)

| Slice | Content | Files (estimate) | Protected | Depends on | Gate |
|---|---|---|---|---|---|
| **S1** | The notifier (AD-1 to AD-13): wrapper, module, `HOS_CYCLE_PROJECT` export, test isolation fixture, docs, registrations | `bootstrap/notify_human.sh` (new), `bootstrap/lib/notify_human.py` (new), `bin/hos-cron` (one export line), `tests/framework/test_notify_human.py` (new), `tests/conftest.py` (AD-7 fixture), `tests/automation/test_hos_cron.py` (export pin), `docs/CRON-SETUP.md`, `scripts/framework/framework_consumer_files.txt`, `SCRIPTS-INDEX.md`, `CLAUDE.md`: **10** | Yes: `bootstrap/**`, `bin/**`, `CLAUDE.md` | Nothing. Designed on ESC-1 (B) | Human approval. `security-reviewer`, `privacy-reviewer`, `reliability-reviewer` and `ops-reviewer` mandatory. The PR body discloses R-1 to R-6, the `bin/hos-cron` conflict notice and AM-1 |
| **S2** | "Cron cannot start" triggers (AD-14): `token-mint-failed`, `cron-lock-stuck`, `usage-pause-fail-closed` | `bin/hos-cron`, `bin/lib/notify_triggers.py` (new), `tests/automation/test_hos_cron.py` or a new focused test, `tests/framework/test_notify_triggers.py` (new), `docs/CRON-SETUP.md`, `SCRIPTS-INDEX.md`: about 6 | Yes | S1, **ESC-2** | Human approval. `reliability-reviewer` mandatory. Conflict notice for `bin/hos-cron` |
| **S3a** | `worker-idle` (AD-14) | `bin/hos-cron`, `bin/lib/notify_triggers.py`, tests, docs: about 4 | Yes | S2 (shares the counter module), **ESC-3**, **ESC-4** | Human approval. `reliability-reviewer` |
| **S3b** | `needs-human-stale` detector (AD-14) | a new `scripts/automation/` module, its tests, the `bin/hos-cron` call site, docs: about 5 | Yes | S1, **ESC-4**. Check whether #1928's attention pass is on `main` | Human approval. `reliability-reviewer`, `privacy-reviewer` (it reads comment authorship) |

**Order:** S1 first, then S2, then S3a and S3b (S3a and S3b in either order). The cross-issue callers (ADR-2100 S2, ADR-1605 Part 3, #2123) are independent. Each one goes live when S1 lands, with no change on their side.

**Optional TD subdivision.** If S1's TD exceeds the inner-loop budget, it may split S1 into S1a (module, wrapper, tests, consumer list, index) and S1b (docs, CLAUDE.md, the `bin/hos-cron` export). S1a must not merge without S1b's export if any cross-issue caller has already merged by then (AD-10).

---

## 6. Requirement amendments (for pm-agent to record. The requirements file is not edited here: none of these corrects a factual error)

- **AM-1 (REQ-4, REQ-1).** Under ESC-1 (B), the notifier never opens `--body-file`, so "an unreadable `--body-file`" is **not** a usage error. Under (A), a failed body read degrades to sending without the extra line. Rationale: an ignored or optional input must never cause a lost push (AD-2).
- **AM-2 (REQ-1, REQ-10).** The project variable is named `HOS_CYCLE_PROJECT`, and it is exported by `bin/hos-cron` in S1 (AD-10). The test-override variables are named `HOS_NOTIFY_TEST_ENDPOINT` and `HOS_NOTIFY_TEST_CREDENTIALS`. The endpoint override is **loopback-only**, and the credentials override must not be the real credentials file (AD-7). That is stricter than REQ-10.
- **AM-3 (REQ-4, REQ-12).** The stdout grammar and the closed reason vocabulary are those of AD-3. REQ-12's `credentials|delivery|timeout|state` set is replaced by the AD-3 tokens. A state problem is never a `failed` reason, because the notifier sends anyway. It appears as `state=unusable|untrusted` (AD-11).
- **AM-4 (REQ-5).** The credentials path is resolved from the **passwd** home, not `$HOME` (AD-4).
- **AM-5 (REQ-15, for S2).** `cron-lock-stuck` is one call per age-based reclaim, made by the observing process. The "could not acquire after reclaim" branch is not a second trigger (AD-14).

---

## 7. Product-boundary checkpoint, startup gap and affected sign-offs

- **Cleared by the human's ruling:**
  - the new third-party egress path (`api.pushover.net`);
  - the new credential and its location;
  - the unsandboxed caller;
  - the trigger list;
  - the 6 h window;
  - the message template (cause, issue URL, `--since`).
  
  ADR-2100 and ADR-1605 already cleared the three added causes and the pointer-only payload.
- **Architect decisions with a product or operational consequence, routed to the human (§8):**
  - ignoring proxy settings (R-4, ARCH-ESC-1);
  - accepting working-tree execution of credential-holding code for v0.7.0 (R-1, ARCH-ESC-2).
  
  Neither blocks S1's TD. Both must be visible at S1's human merge gate, and the PR body discloses them. The remaining architect decisions are AD-2's ignored body file, AD-3's dedup-is-success rule, AD-4's passwd home, AD-7's loopback-only rule and AD-8's lock semantics. Each either tightens security or errs toward more pushes, and changes nothing a human would experience as reduced coverage.
- **Startup gap.** This is the initial architecture review for #2125, so it is not a reactive revision. No design or code exists against any prior #2125 ADR.
- **Cross-issue consistency (affected sign-offs).** Each existing approval was checked against this ADR:
  - **ADR-2100 AD-9 and AD-11 stand.** The AC-40 shape with `--issue <n>|none --priority high --body-file` is accepted. The notifier writes nothing under `TMPDIR` and finishes within its per-call share of the 120 s step (25 s at most). Its `issue=none` constant is supplied by the notifier (AD-9). No ADR-2100 S2 design text needs to change.
  - **ADR-1605 AD-20 and TD-1605 §15.7 and §15.8 stand.** The argv, the `--url` workflow form, `env -i` plus the allowlist, the 30 s bound and the exit mapping all work unchanged. The "#2125 variables to add" list is empty (AD-12). R-3 is the only behavioural note, and AC-40 assigns it to #2125.
  - **ADR-1944 A6-4 stands.** The priority constants mirror it (AD-9).
  - No existing sign-off is orphaned.

---

## 8. Open questions

### pm-agent's ESCs: classification and rulings

| ESC | Product or architecture | Ruling / recommendation | Blocks |
|---|---|---|---|
| **ESC-1** (body-file content) | **Product.** It decides what text leaves the machine to a third party, which is the data-retention and privacy surface. | **Recommend (B)**, matching pm. S1 is designed on (B). Moving to (A) is a bounded TD delta: AD-2's bounded first-line read, AD-9's 200-character renderer cap, and AC-11's fixture. It touches no other AD. | **Not S1's TD.** S1's *merge* should wait for the ruling, or merge on (B) and amend later. |
| **ESC-2** (single transient failure pages?) | **Product** for the policy and the value of K, because paging at a priority that bypasses quiet hours is user-visible. **Architecture** for the mechanism, decided in AD-14: a Python counter, untrusted state errs loud, and K is a named constant. | **Recommend (A), K = 2**, matching pm. | S2 only |
| **ESC-3** (N for worker-idle) | **Product** (user-visible timing). | **Recommend (A), N = 8**, matching pm. N is a named constant in `notify_triggers.py`. | S3a only |
| **ESC-4** ("parked") | **Product.** It decides what counts as noise, and (B) is a new label-governance decision. | **Recommend (A)**, matching pm. Architecture note: under (A), S3a and S3b call the selector's own exclusion predicate and do not copy it (AD-14, D41). | S3a, S3b |

### Architecture questions routed to the human (product consequence of an architect decision)

- **ARCH-ESC-1 (operational): proxy policy.** Decided provisionally: the notifier ignores proxy settings (AD-5). That keeps delivery identical across callers and avoids environment-driven routing. **Recommendation: confirm.** If this host ever needs a proxy, a dedicated `HOS_NOTIFY_HTTPS_PROXY` (TLS still verified end to end) is the bounded alternative. **Blocks nothing.** It is disclosed at S1 merge.
- **ARCH-ESC-2 (security posture): R-1.** **Recommendation: accept for v0.7.0** (same class as `get_app_token.sh` and the App PEM), and record "run the notifier from ADR-1605's main extraction" as a follow-up once ADR-1605 Part 3's extraction exists. The alternative is to block S1 on that extraction, which would leave every pre-auth alert path without a channel until #1605 Part 3 lands. **Does not block S1's TD.** The human answers it at S1's merge gate.

---

## 9. Handed to `technical-design` (S1)

- **TD-H1.** Pin the AD-3 stdout regex and reason vocabulary in one test. Map every §3 row to a test.
- **TD-H2.** Set the AD-6 sub-budgets (at or below the stated ceilings), and show their sum with margin under 25 s.
- **TD-H3.** Implement AD-8's lock-then-verify-inode loop and the prune rule. The concurrency test (AC-9) starts two processes on one key against a fake endpoint that blocks until both have started, and asserts that exactly one request is received.
- **TD-H4.** Specify the fake endpoint, a loopback `http.server` thread with configurable status, body and delay. Use it for AC-1, AC-2, AC-5 and AC-12.
- **TD-H5.** For AC-7 and AC-8, record `subprocess` argv and environment and `os.open` paths during a send, and assert that no credential value appears and that the default credentials path is never opened while overridden.
- **TD-H6.** Write the `merge_config.resolve_repo_slug` parity test (AD-9) over SSH, HTTPS, `.git`-suffixed and malformed remotes.
- **TD-H7.** Write the static tests: no TLS-disabling identifiers, no `subprocess` in the send path, no priority other than 0 or 1, no `traceback` printing, and an exact closed form-field set.
- **TD-H8.** Write the ESC-1 (A) delta as an appendix, so a ruling of (A) is a mechanical change.
- **TD-H9.** Write the AD-10 export pin in `tests/automation/test_hos_cron.py`: `HOS_CYCLE_PROJECT` is exported with the raw project key, and exactly once.

## 10. Notes and follow-ups (named, not filed here)

- **N-1.** `bootstrap/get_app_token.sh:143-193` passes the App JWT in curl's argv (AF-1). The JWT is short-lived, but the value is visible to local users through `/proc`. A candidate fix is `curl --config -` or `-H @-` from stdin. This is outside #2125, and the worker should file it.
- **N-2.** Once ADR-1605 Part 3's extraction exists, run the notifier from it (R-1, ARCH-ESC-2).
- **N-3.** When #1944 S4 is designed, it should match AD-9's message shape and consider `notify_human.sh` as its fallback (REQ §3, issue item 7). This is pm's annotation obligation on #1944, restated here.

---

## Escalation flag (CORE self-flag)

- **RISK: HIGH** for the feature, and MEDIUM for this document (docs only). The built feature adds a third-party egress path and a credential on a protected surface, and a pre-auth call path in `bin/hos-cron`. The highest-consequence decisions are AD-4 (credential handling), AD-5 (transport), AD-7 (the override cannot carry the real token) and AD-8 (dedup must never turn into silence).
- **CONFIDENCE: HIGH** on the cross-issue consistency in §7 and on AF-1 to AF-9. The caller contracts, the line numbers and the reuse candidates were read directly at `5206c393a`. **MEDIUM-HIGH** on AD-6 and AD-8. The thread-deadline and lock-on-record patterns are standard, but no existing HOS code exercises them together, so TD-H2 and TD-H3 carry the proof. Pushover's response shape (`status: 1`) and its 4xx behaviour come from its public API documentation, not from a live call here. `--test` against the real endpoint is the human's post-merge confirmation.
- **BLAST RADIUS:** two new `bootstrap/` files, one line in `bin/hos-cron`, `tests/conftest.py` (session-wide, so it affects every test that might reach the notifier), `docs/CRON-SETUP.md`, the consumer file list, `SCRIPTS-INDEX.md` and `CLAUDE.md`. When S1 lands, the three cross-issue callers' "absent" path becomes live.
- **Change classification: STRUCTURAL, human-issued.** The channel, the credential and the triggers are the human's. The architect's own additions are ADDITIVE and tightening: AD-7's loopback rule, AD-4's passwd home, AD-8's lock semantics, AD-3's closed vocabulary, AD-10's export and AM-1 to AM-5. Two architect decisions carry operational or product consequences and are routed to the human (ARCH-ESC-1, ARCH-ESC-2).

## Human Review Required

1. **ESC-1 to ESC-4** (product). All four are open, and the recommendations match pm-agent's: B, A with K = 2, A with N = 8, and A. Only ESC-1 touches S1, and S1's TD proceeds on (B).
2. **ARCH-ESC-1** (proxy policy) and **ARCH-ESC-2** (accept R-1 for v0.7.0). Both are answerable at S1's merge gate, and neither blocks S1's TD.
3. **Human acts, not questions:** after S1 merges, provision `~/.config/hos/pushover.env` (mode 600) and run `bootstrap/notify_human.sh --test`.
