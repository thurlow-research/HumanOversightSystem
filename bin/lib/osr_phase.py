"""Budget accounting, strike state and context-block rendering for the overseer second-review
phase of bin/hos-cron (#2357, TD-2357-S1b).

bin/hos-cron owns process control (timeouts, kills, labels); this helper owns every decision
that parses text. It reads the runner's one JSON line as untrusted data, validates it against
the closed vocabulary below, and renders only values that came out of that validation.

Invoked as `python3 -I bin/lib/osr_phase.py <subcommand> ...`. Python 3.9-compatible syntax,
standard library only, and it must not import scripts.automation.lib: the vocabularies are
duplicated literals pinned against the runner's by tests/automation/test_osr_phase.py.

Subcommands print one machine-readable result on stdout and exit 0; 2 is a usage error and 1
is any other failure. The caller treats every non-zero exit as a phase error and fails closed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
import tempfile
import time
import traceback

# --------------------------------------------------------------------------- #
# Vocabulary (duplicated from scripts/automation/lib/overseer_second_review.py)#
# --------------------------------------------------------------------------- #
TIERS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
VENDORSETS = ("none", "agy", "agy+codex")
VERDICTS = ("approve", "request_changes", "not-required", "hold", "pending", "skipped-held")
FINAL_VERDICTS = ("approve", "request_changes", "not-required")
FINAL_REASON_FOR_VERDICT = {
    "approve": "ok",
    "request_changes": "findings",
    "not-required": "tier-below-medium",
}
_VENDOR_HOLD_TOKENS = (
    "vendor-unavailable",
    "vendor-error",
    "vendor-timeout",
    "vendor-missing",
    "prompt-not-consumed",
)
HOLD_REASONS = frozenset(
    ["%s:%s" % (token, vendor) for token in _VENDOR_HOLD_TOKENS for vendor in ("agy", "codex")]
    + [
        "unparseable",
        "diff-too-large",
        "empty-diff",
        "review-inconsistent",
        "pending-stuck",
        "binary-unreviewed",
    ]
)
PENDING_COUNTED = frozenset(
    ["fetch-failed", "base-unresolved", "lock-unavailable", "review-failed", "diff-failed"]
)
PENDING_UNCOUNTED = frozenset(
    [
        "untrusted-checkout",
        "budget",
        "head-moved",
        "lock-busy",
        "pr-not-found",
        "pr-not-open",
        "github-error",
        "config-error",
        "state-write-failed",
    ]
)
RESULT_KEYS = frozenset(
    [
        "check",
        "schema",
        "pr",
        "head_sha",
        "base_sha",
        "range",
        "tier",
        "vendors",
        "verdict",
        "status",
        "reason",
        "reused",
        "findings_file",
        "record",
        "hold_label_applied",
        "pending_count",
        "pending_last_reason",
    ]
)

# Uncounted by the runner, so the phase counts them (TD 6.6, AR1).
RUNNER_STRIKE_REASONS = frozenset(
    ["lock-busy", "state-write-failed", "config-error", "github-error", "untrusted-checkout"]
)
# Neither a strike nor a reset: bounded by ordering, by the head, or by the PR leaving the set.
NEUTRAL_REASONS = frozenset(["budget", "head-moved", "pr-not-found", "pr-not-open"])
# Strikes the phase itself synthesizes with no runner call, and holds it synthesizes outright.
SYNTHETIC_STRIKES = frozenset(["untrusted-checkout", "runner-unbounded"])
SYNTHETIC_HOLDS = frozenset(["config-error", "phase-error"])

HELD_LABELS = frozenset(["needs-human", "hos-halt"])
STRIKE_LIMIT = 3
MAX_RUNNER_STDOUT = 64 * 1024
LABELS = ("applied", "failed", "existing")

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_PR_RE = re.compile(r"^[1-9][0-9]{0,6}$")
_FINDINGS_PATH_RE = re.compile(r"^/[A-Za-z0-9._/+-]{1,512}$")
_REASON_RE = re.compile(r"^[a-z0-9:-]{1,64}$")
LINE_RE = re.compile(
    r"^OSR pr=#[1-9][0-9]{0,6} head=([0-9a-f]{40}|-) base=([0-9a-f]{40}|-) "
    r"tier=(LOW|MEDIUM|HIGH|CRITICAL|-) vendors=(none|agy|agy\+codex|-) "
    r"verdict=(approve|request_changes|not-required|hold|pending|skipped-held) "
    r"reason=[a-z0-9:-]{1,64} findings_file=(/[A-Za-z0-9._/+-]{1,512}|-) "
    r"reused=(true|false) persisted=(true|false|-) count=([1-9][0-9]{0,5}|-) "
    r"last_reason=([a-z0-9:-]{1,64}|-) label=(applied|failed|existing|-)$"
)
HEADER = "[hos-cron overseer second review (#2357)]"
TERMINATOR = "---"


def _warn(message):
    sys.stderr.write("osr_phase: WARN %s\n" % message)


def _is_int(value, expected=None):
    return type(value) is int and (expected is None or value == expected)


def _is_str_in(value, allowed):
    return isinstance(value, str) and value in allowed


# --------------------------------------------------------------------------- #
# Files: private reads, atomic writes                                         #
# --------------------------------------------------------------------------- #
def _read_private_json(path, max_bytes=1 << 20):
    """The parsed dict, or None for a missing, unsafe or malformed file (with a WARN when the
    file exists but is untrusted). Refuses symlinks and any file this uid does not own."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        _warn("cannot open %s (%s)" % (os.path.basename(path), type(exc).__name__))
        return None
    try:
        st = os.fstat(fd)
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_size > max_bytes
            or st.st_uid != os.geteuid()
            or st.st_mode & 0o077
        ):
            _warn("untrusted state file %s ignored" % os.path.basename(path))
            return None
        data = os.read(fd, max_bytes + 1)
    except OSError as exc:
        _warn("cannot read %s (%s)" % (os.path.basename(path), type(exc).__name__))
        return None
    finally:
        os.close(fd)
    try:
        obj = json.loads(data.decode("utf-8"))
    except ValueError:
        _warn("malformed state file %s ignored" % os.path.basename(path))
        return None
    return obj if isinstance(obj, dict) else None


def _atomic_write_json(path, obj):
    parent = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(obj, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- #
# Strike and defer state (TD section 4)                                       #
# --------------------------------------------------------------------------- #
def _strike_dir(state_dir):
    return os.path.join(state_dir, "strikes")


def _strike_path(state_dir, pr):
    return os.path.join(_strike_dir(state_dir), "pr%d.json" % pr)


def _load_strike(state_dir, pr):
    """The stored strike, or None. A file that cannot be trusted counts as no strikes."""
    raw = _read_private_json(_strike_path(state_dir, pr))
    if raw is None:
        return None
    head = raw.get("head")
    if (
        _is_int(raw.get("schema"), 1)
        and _is_int(raw.get("pr"), pr)
        and _is_int(raw.get("count"))
        and raw["count"] >= 1
        and (head is None or (isinstance(head, str) and _HEX40.match(head)))
    ):
        return raw
    _warn("malformed strike file for pr %d ignored" % pr)
    return None


def _write_strike(state_dir, pr, head, count, last_reason):
    os.makedirs(_strike_dir(state_dir), mode=0o700, exist_ok=True)
    _atomic_write_json(
        _strike_path(state_dir, pr),
        {
            "schema": 1,
            "pr": pr,
            "head": head,
            "count": count,
            "last_reason": last_reason,
            "updated_at": _utc_now(),
        },
    )


def _delete_strike(state_dir, pr):
    try:
        os.unlink(_strike_path(state_dir, pr))
    except FileNotFoundError:
        pass
    except OSError as exc:
        _warn("could not delete the strike file for pr %d (%s)" % (pr, type(exc).__name__))


def _deferred_path(state_dir):
    return os.path.join(state_dir, "deferred.json")


def _load_deferred(state_dir):
    raw = _read_private_json(_deferred_path(state_dir))
    prs = raw.get("prs") if raw is not None else None
    if not (isinstance(prs, list) and all(_is_int(n) and n > 0 for n in prs)):
        return []
    return list(prs)


def _store_deferred(state_dir, prs):
    try:
        os.makedirs(state_dir, mode=0o700, exist_ok=True)
        _atomic_write_json(_deferred_path(state_dir), {"schema": 1, "prs": sorted(set(prs))})
    except OSError as exc:
        _warn("could not record deferred PRs (%s)" % type(exc).__name__)


def _defer(state_dir, pr):
    current = _load_deferred(state_dir)
    if pr not in current:
        _store_deferred(state_dir, current + [pr])


def _undefer(state_dir, pr):
    current = _load_deferred(state_dir)
    if pr in current:
        _store_deferred(state_dir, [n for n in current if n != pr])


# --------------------------------------------------------------------------- #
# Validating the runner's line (TD 5.3)                                       #
# --------------------------------------------------------------------------- #
def _hex_or_none(value):
    return value is None or (isinstance(value, str) and bool(_HEX40.match(value)))


def _under(path, root):
    """True when `path` is a normalized absolute path whose real location is inside `root`."""
    if not (isinstance(path, str) and os.path.isabs(path) and os.path.normpath(path) == path):
        return False
    real_root = os.path.realpath(root).rstrip("/") + "/"
    return os.path.realpath(path).startswith(real_root)


def _count_problem(result):
    """The pending_count / pending_last_reason presence rule (TD 5.3 item 9)."""
    verdict, reason = result["verdict"], result["reason"]
    count, last = result["pending_count"], result["pending_last_reason"]
    counted = verdict == "pending" and reason in PENDING_COUNTED
    stuck = verdict == "hold" and reason == "pending-stuck" and result["reused"] is False
    if counted:
        count_ok = count is None or (_is_int(count) and count >= 1)
    elif stuck:
        count_ok = _is_int(count) and count >= STRIKE_LIMIT
    else:
        count_ok = count is None
    if not count_ok:
        return "pending_count"
    if (count is None) != (last is None):
        return "pending_last_reason"
    if last is not None and not _is_str_in(last, PENDING_COUNTED):
        return "pending_last_reason"
    return None


def validate_result(result, pr, runs_dir):
    """The first problem found in a decoded runner result, or None when it is acceptable."""
    if set(result) != RESULT_KEYS:
        return "keys"
    if not (
        result["check"] == "second-review"
        and _is_int(result["schema"], 1)
        and _is_int(result["pr"], pr)
    ):
        return "identity"
    head, base, rng = result["head_sha"], result["base_sha"], result["range"]
    if not (_hex_or_none(head) and _hex_or_none(base)):
        return "sha"
    if rng is not None and not (
        base is not None and head is not None and rng == "%s..%s" % (base, head)
    ):
        return "range"
    tier, vendors = result["tier"], result["vendors"]
    if tier is not None and not _is_str_in(tier, TIERS):
        return "tier"
    if vendors is not None and not _is_str_in(vendors, VENDORSETS):
        return "vendors"
    if tier is not None and vendors is None:
        return "vendors"
    verdict, status, reason = result["verdict"], result["status"], result["reason"]
    if not _is_str_in(verdict, VERDICTS):
        return "verdict"
    if not isinstance(result["reused"], bool):
        return "reused"
    if verdict in FINAL_VERDICTS:
        status_ok = status == "final" and reason == FINAL_REASON_FOR_VERDICT[verdict]
    elif verdict == "hold":
        status_ok = status == "hold" and _is_str_in(reason, HOLD_REASONS)
    elif verdict == "pending":
        status_ok = status is None and (
            _is_str_in(reason, PENDING_COUNTED) or _is_str_in(reason, PENDING_UNCOUNTED)
        )
    else:
        status_ok = status is None and reason == "held-label"
    if not status_ok:
        return "status-reason"

    findings = result["findings_file"]
    if (findings is not None) != (verdict == "request_changes"):
        return "findings_file"
    if findings is not None and not (
        isinstance(findings, str)
        and _FINDINGS_PATH_RE.match(findings)
        and _under(findings, runs_dir)
    ):
        return "findings_file"

    # A record exists for every final result and every persisted hold. Only the pending-stuck
    # hold may lack one (TD-2357-S1a 5.7 step 4c); a pending or skipped-held result never has one.
    record = result["record"]
    optional = verdict == "hold" and reason == "pending-stuck"
    required = verdict in FINAL_VERDICTS or (verdict == "hold" and not optional)
    if record is None and required:
        return "record"
    if record is not None and not (required or optional):
        return "record"
    records_dir = os.path.join(os.path.dirname(os.path.normpath(runs_dir)), "records")
    if record is not None and not (
        isinstance(record, str)
        and os.path.isabs(record)
        and os.path.normpath(record) == record
        and record.startswith(records_dir + "/")
    ):
        return "record"

    applied = result["hold_label_applied"]
    if verdict == "hold" and record is not None:
        if not isinstance(applied, bool):
            return "hold_label_applied"
    elif applied is not None:
        return "hold_label_applied"
    return _count_problem(result)


def parse_runner_stdout(raw):
    """(result, None) for exactly one JSON object line of at most 64 KiB, else (None, token)."""
    if len(raw) > MAX_RUNNER_STDOUT:
        return None, "oversize"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "encoding"
    if text.endswith("\n"):
        text = text[:-1]
    if not text or "\n" in text or "\r" in text:
        return None, "not-one-line"

    def no_duplicates(pairs):
        keys = [k for k, _ in pairs]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate key")
        return dict(pairs)

    try:
        obj = json.loads(text, object_pairs_hook=no_duplicates)
    except ValueError:
        return None, "json"
    if not isinstance(obj, dict):
        return None, "not-an-object"
    return obj, None


# --------------------------------------------------------------------------- #
# Lines                                                                       #
# --------------------------------------------------------------------------- #
def _dash(value):
    return "-" if value is None else str(value)


def _bool_word(value):
    return "-" if value is None else ("true" if value else "false")


def render_line(fields):
    """The OSR line for one PR, from a dict of line fields. Raises ValueError when the result
    does not match the closed grammar, so no unvalidated text can reach the prompt."""
    tier = fields.get("tier")
    vendors = fields.get("vendors") if tier is not None else None
    line = (
        "OSR pr=#%s head=%s base=%s tier=%s vendors=%s verdict=%s reason=%s findings_file=%s "
        "reused=%s persisted=%s count=%s last_reason=%s label=%s"
        % (
            fields.get("pr"),
            _dash(fields.get("head")),
            _dash(fields.get("base")),
            _dash(tier),
            _dash(vendors),
            fields.get("verdict"),
            fields.get("reason"),
            _dash(fields.get("findings_file")),
            "true" if fields.get("reused") is True else "false",
            _bool_word(fields.get("persisted")),
            _dash(fields.get("count")),
            _dash(fields.get("last_reason")),
            _dash(fields.get("label")),
        )
    )
    if not LINE_RE.match(line):
        raise ValueError("line does not match the OSR grammar")
    return line


def _blank_line(pr, verdict, reason, **over):
    """A phase-synthesized line: no runner data, so every SHA, tier and path is empty."""
    fields = {
        "pr": pr,
        "head": None,
        "base": None,
        "tier": None,
        "vendors": None,
        "verdict": verdict,
        "reason": reason,
        "findings_file": None,
        "reused": False,
        "persisted": False if verdict == "hold" else None,
        "count": None,
        "last_reason": None,
        "label": None,
    }
    fields.update(over)
    return fields


def _line_from_result(result):
    verdict = result["verdict"]
    fields = _blank_line(
        result["pr"],
        result["verdict"],
        result["reason"],
        head=result["head_sha"],
        base=result["base_sha"],
        tier=result["tier"],
        vendors=result["vendors"],
        findings_file=result["findings_file"],
        reused=result["reused"],
        persisted=(result["record"] is not None) if verdict in FINAL_VERDICTS + ("hold",) else None,
        count=result["pending_count"],
        last_reason=result["pending_last_reason"],
    )
    return fields


def _scratch_line_path(scratch, pr):
    return os.path.join(scratch, "pr%d.line.json" % pr)


def _save_line(scratch, fields):
    with open(_scratch_line_path(scratch, fields["pr"]), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(fields, sort_keys=True) + "\n")


def _load_line(scratch, pr):
    with open(_scratch_line_path(scratch, pr), encoding="utf-8") as fh:
        loaded = json.load(fh)
    if not isinstance(loaded, dict):
        raise ValueError("line file is not an object")
    return loaded


# --------------------------------------------------------------------------- #
# Strikes                                                                     #
# --------------------------------------------------------------------------- #
def _strike(state_dir, pr, reason, head, base=None, tier=None, vendors=None):
    """Count one strike. Returns (line fields, needs_label)."""
    prior = _load_strike(state_dir, pr)
    count = prior["count"] if prior else 0
    if prior and prior.get("head") and head and prior["head"] != head:
        count = 0
    count += 1
    stored_head = head or (prior.get("head") if prior else None)
    shared = {"head": head, "base": base, "tier": tier, "vendors": vendors}
    try:
        _write_strike(state_dir, pr, stored_head, count, reason)
    except OSError as exc:
        _warn("could not write the strike file for pr %d (%s)" % (pr, type(exc).__name__))
        return _blank_line(pr, "hold", "state-write-failed", **shared), True
    if count >= STRIKE_LIMIT:
        return (
            _blank_line(pr, "hold", "pending-stuck", count=count, last_reason=reason, **shared),
            True,
        )
    return (
        _blank_line(pr, "pending", reason, count=count, last_reason=reason, **shared),
        False,
    )


def _stderr_excerpt(path):
    """A printable-ASCII excerpt of the runner's stderr for the cron log (never control bytes)."""
    if not path:
        return ""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(300)
    except OSError:
        return ""
    return "".join(chr(b) if 32 <= b < 127 else " " for b in raw).strip()


def _ingest(args):
    """Returns (line fields, needs_label, uncached). A hold on a PR that already carries a
    hold label renders label=existing and needs no label call."""
    line, needs_label, uncached = _ingest_result(args)
    if args.held and line["verdict"] == "hold":
        line["label"] = "existing"
        needs_label = False
    return line, needs_label, uncached


def _ingest_result(args):
    pr, state_dir = args.pr, args.state_dir
    if args.synthetic:
        if args.synthetic in SYNTHETIC_HOLDS:
            return _blank_line(pr, "hold", args.synthetic), True, False
        line, needs_label = _strike(state_dir, pr, args.synthetic, None)
        return line, needs_label, False

    uncached_on_failure = not args.cache_only
    if args.rc != 0:
        _warn("runner for pr %d exited %d: %s" % (pr, args.rc, _stderr_excerpt(args.err)))
        line, needs_label = _strike(state_dir, pr, "runner-failed", None)
        return line, needs_label, uncached_on_failure
    try:
        with open(args.out, "rb") as fh:
            raw = fh.read(MAX_RUNNER_STDOUT + 1)
    except OSError:
        raw = b""
    result, problem = parse_runner_stdout(raw)
    if result is not None:
        problem = validate_result(result, pr, args.runs_dir)
    if problem is not None:
        _warn("runner output for pr %d rejected (%s)" % (pr, problem))
        line, needs_label = _strike(state_dir, pr, "invalid-line", None)
        return line, needs_label, uncached_on_failure

    verdict, reason = result["verdict"], result["reason"]
    uncached = (
        not args.cache_only
        and result["reused"] is not True
        and verdict not in ("not-required", "skipped-held")
    )
    line = _line_from_result(result)
    if verdict == "skipped-held":
        return line, False, uncached
    if verdict == "pending":
        if reason == "budget":
            _defer(state_dir, pr)
            return line, False, uncached
        if reason in NEUTRAL_REASONS:
            return line, False, uncached
        counted_with_count = reason in PENDING_COUNTED and result["pending_count"] is not None
        if not counted_with_count:
            head, base = result["head_sha"], result["base_sha"]
            line, needs_label = _strike(
                state_dir, pr, reason, head, base, result["tier"], result["vendors"]
            )
            _undefer(state_dir, pr)
            return line, needs_label, uncached
    _delete_strike(state_dir, pr)
    _undefer(state_dir, pr)
    return line, verdict == "hold", uncached


# --------------------------------------------------------------------------- #
# Subcommands                                                                 #
# --------------------------------------------------------------------------- #
def _pr_arg(value):
    if not _PR_RE.match(value):
        raise argparse.ArgumentTypeError("must be an integer in 1..9999999")
    return int(value)


def _pr_list(value):
    items = value.split()
    for item in items:
        if not _PR_RE.match(item):
            raise argparse.ArgumentTypeError("not a PR number list: %r" % value)
    return [int(item) for item in items]


def _flag(value):
    if value not in ("0", "1"):
        raise argparse.ArgumentTypeError("must be 0 or 1")
    return value == "1"


def _nonneg_int(value):
    if not re.match(r"^[0-9]{1,9}$", value):
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return int(value)


def cmd_order(args):
    deferred = _load_deferred(args.state_dir)
    wanted = set(args.prs)
    first = sorted(n for n in set(deferred) if n in wanted)
    rest = sorted(wanted.difference(first))
    print(" ".join(str(n) for n in first + rest))
    return 0


def cmd_budget(args):
    if not args.uncached_ran or args.elapsed + args.per_pr <= args.budget:
        print("RUN")
    else:
        print("CACHE_ONLY")
    return 0


def cmd_ingest(args):
    line, needs_label, uncached = _ingest(args)
    _save_line(args.scratch, line)
    print("ACTION=%s UNCACHED=%d" % ("label" if needs_label else "none", 1 if uncached else 0))
    return 0


def cmd_label_result(args):
    fields = _load_line(args.scratch, args.pr)
    fields["label"] = args.result
    _save_line(args.scratch, fields)
    return 0


def cmd_mark_args(args):
    fields = _load_line(args.scratch, args.pr)
    head = fields.get("head")
    if fields.get("persisted") is True and isinstance(head, str) and _HEX40.match(head):
        print("MARK=%s" % head)
    else:
        print("MARK=none")
    return 0


def cmd_render(args):
    held = set(args.held)
    out = [HEADER]
    for pr in args.prs:
        if pr in held:
            fields = _blank_line(pr, "skipped-held", "held-label", persisted=None)
        else:
            fields = _load_line(args.scratch, pr)
            if fields.get("pr") != pr:
                raise ValueError("line file is for another PR")
        out.append(render_line(fields))
    out.append(TERMINATOR)
    sys.stdout.write("\n".join(out) + "\n")
    return 0


def cmd_held(args):
    """Reads the PR detail JSON on stdin; prints 1 when the PR carries a hold label, else 0.
    A detail that cannot be read counts as not held: the runner re-reads the labels itself."""
    try:
        detail = json.load(sys.stdin)
        labels = detail.get("labels") if isinstance(detail, dict) else None
        names = {n for n in labels if isinstance(n, str)} if isinstance(labels, list) else set()
    except ValueError:
        names = set()
    print("1" if HELD_LABELS & names else "0")
    return 0


def cmd_defer(args):
    _defer(args.state_dir, args.pr)
    return 0


def _build_parser():
    parser = argparse.ArgumentParser(prog="osr_phase", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("order", help="PRs in processing order: deferred first, then ascending")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--prs", type=_pr_list, required=True)
    p.set_defaults(func=cmd_order)

    p = sub.add_parser("budget", help="RUN or CACHE_ONLY for the next PR")
    p.add_argument("--elapsed", type=_nonneg_int, required=True)
    p.add_argument("--uncached-ran", type=_flag, required=True)
    p.add_argument("--per-pr", type=_nonneg_int, required=True)
    p.add_argument("--budget", type=_nonneg_int, required=True)
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("ingest", help="validate one runner result and record its line")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--runs-dir")
    p.add_argument("--pr", type=_pr_arg, required=True)
    p.add_argument("--rc", type=int)
    p.add_argument("--cache-only", type=_flag, default=False)
    p.add_argument("--held", type=_flag, default=False)
    p.add_argument("--out")
    p.add_argument("--err")
    p.add_argument("--scratch", required=True)
    p.add_argument(
        "--synthetic",
        choices=sorted(SYNTHETIC_STRIKES | SYNTHETIC_HOLDS),
        help="no runner call: strike or hold the PR with this reason",
    )
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("label-result", help="record whether needs-human was applied")
    p.add_argument("--scratch", required=True)
    p.add_argument("--pr", type=_pr_arg, required=True)
    p.add_argument("--result", choices=("applied", "failed"), required=True)
    p.set_defaults(func=cmd_label_result)

    p = sub.add_parser("mark-args", help="the head to pass to mark-hold-label, or none")
    p.add_argument("--scratch", required=True)
    p.add_argument("--pr", type=_pr_arg, required=True)
    p.set_defaults(func=cmd_mark_args)

    p = sub.add_parser("render", help="the context block for the overseer prompt")
    p.add_argument("--scratch", required=True)
    p.add_argument("--prs", type=_pr_list, required=True)
    p.add_argument("--held", type=_pr_list, default=[])
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("held", help="1 when the PR detail on stdin carries a hold label")
    p.set_defaults(func=cmd_held)

    p = sub.add_parser("defer", help="run this PR first next cycle")
    p.add_argument("--state-dir", required=True)
    p.add_argument("--pr", type=_pr_arg, required=True)
    p.set_defaults(func=cmd_defer)
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    if args.command == "ingest":
        if not args.synthetic and (args.rc is None or args.out is None or args.runs_dir is None):
            _build_parser().error("ingest needs --rc, --out and --runs-dir unless --synthetic")
    try:
        return args.func(args)
    except Exception:  # noqa: BLE001 - the contract is exit 1 and a traceback on stderr
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
