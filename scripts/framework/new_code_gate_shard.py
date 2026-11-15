"""Pure sharding logic of the new-code gate (#2304, TD 5.20; ADR-2304 section 2h, AD-14).

The mutation phase is split over `N` shards that run as separate CI jobs. This module holds
everything about that split that is decidable from data alone: the cost model and shard
count, the partition, the plan and fragment hashes, fragment validation and the merge that
turns a plan and its fragments into the records `decide` reads.

It does no I/O and reads no clock or environment: the CLI (`new_code_gate.py`) reads the
directories, runs the shards and passes parsed documents in. At module level it imports only
the stdlib and the pure-logic module. Its module-level and class-level statements hold no
decision logic, because the gate's own PR gates this file in full (TD 5.19).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from scripts.framework import new_code_gate_logic as ncg

GateError = ncg.GateError

# Constants of the cost model and the partition (TD 5.20.4). None is read from env, label or config
# (REQ-38, AC-35). The numbers are exact integers, so boundary cases are exact (AC-29).
T_MS = 900_000
N_MAX = 8
CI_CORES = 4
C_MUTANT_MS = 50
D_DEFAULT_MS = 1_000
D_CLAMP_MS = 600_000
STATS_PASSES = 2
COST_MODEL = "per-function-fan-in/1"
MS_PER_MINUTE = 60_000

# What a plan file record carries beyond a cheap-phase record (TD 5.20.6).
PLAN_FILE_EXTRA = (
    "mutant_names",
    "gated_mutant_names",
    "selection_full",
    "function_cost_ms",
    "W_F_ms",
    "fixed_est_ms",
    "cost_ms",
    "to_shards",
)

# Fail codes and reasons a shard can attach to a file: the stats run, the clean run and collection
# are repeated by every shard that holds the file, so they read the same whatever the partition.
SHARD_FAIL_CODES = frozenset(
    {
        "unmarked_repo_copy",
        "path_loaded_module",
        "selected_test_fails_in_isolation",
        "mutation_timeout",
    }
)
SHARD_REASONS = frozenset(
    {
        None,
        "path_load",
        "timeout",
        "blocked_by:unmarked_repo_copy",
        "blocked_by:selected_test_fails_in_isolation",
    }
)
SHARD_STATUSES = frozenset({"complete", "timeout", "internal_error"})
MUTANT_STATUSES = ncg.KILLED_STATUSES | ncg.NOT_KILLED_STATUSES
# The timing keys dropped at any depth when hashing a plan or fragment (ADR-2304 2b condition 5).
# Deliberately its own list, not derived from ncg.UNHASHED_FIELDS: N, plan_hash, shards and
# isolation_failure are hashed here, and no non-timing schema field may reuse one of these names.
DOCUMENT_HASH_DROPS = frozenset(
    {
        "started_at",
        "finished_at",
        "seconds",
        "job_seconds",
        "enumerate_seconds",
        "workspace_seconds",
        "mutmut_seconds",
        "collect_seconds",
    }
)
FRAGMENT_NAME_RE = re.compile(r"^new-code-fragment-([0-9]+)-of-([0-9]+)$")
FINDING_KEYS = ("importer", "loaded_as", "canonical", "via", "phase")
ISOLATION_KEYS = ("stage", "node_ids", "summary_lines", "output_tail")
MAX_FINDINGS = 50


# ---------------------------------------------------------------------------
# Cost model and shard count (TD 5.20.4)
# ---------------------------------------------------------------------------


def ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def shard_count(work_ms: int) -> tuple[int, bool]:
    """`N = min(N_MAX, max(1, ceil(W / T)))` in integers, and whether W exceeds N_MAX shards."""
    count = min(N_MAX, max(1, ceil_div(work_ms, CI_CORES * T_MS)))
    return count, work_ms > N_MAX * CI_CORES * T_MS


def mutant_prefix(name: str) -> str:
    """mutmut's mangled function name for a mutant key (`mangled_name_from_mutant_name`)."""
    return name.partition("__mutmut_")[0]


def clamp_ms(value: int) -> int:
    return min(max(value, 0), D_CLAMP_MS)


def duration_of(test_id: str, durations: Mapping[str, int]) -> int:
    """d(t): measured milliseconds; a container ID sums its children; no entry: the default."""
    if test_id in durations:
        return clamp_ms(durations[test_id])
    children = [clamp_ms(ms) for key, ms in durations.items() if key.startswith(test_id + "::")]
    return sum(children) if children else D_DEFAULT_MS


def executed_by_selected(
    selection: Sequence[str], lines_by_context: Mapping[str, Iterable[int]]
) -> dict[str, frozenset[int]]:
    """The file lines each selected test executed. A container ID takes every context under it."""
    found = {}
    for test_id in selection:
        lines: set[int] = set()
        for context, context_lines in lines_by_context.items():
            if context == test_id or context.startswith(test_id + "::"):
                lines.update(context_lines)
        found[test_id] = frozenset(lines)
    return found


def file_cost(
    path: str,
    selection: Sequence[str],
    method: str,
    durations: Mapping[str, int],
    spans: Mapping[str, tuple[int, int]],
    gated_names: Sequence[str],
    executed: Mapping[str, Iterable[int]],
) -> dict[str, Any]:
    """Per-function fan-in cost of one file (TD 5.20.4, C1).

    A mutant of function f runs only the tests that reach f, so `w_m = C_MUTANT_MS + sum of d(t)`
    over the selected tests that executed a line inside f's span. Without context evidence
    (`name_fallback`) every selected test counts.
    """
    seconds = {t: duration_of(t, durations) for t in selection}
    function_cost: dict[str, int] = {}
    for name in sorted(gated_names):
        prefix = mutant_prefix(name)
        if prefix in function_cost:
            continue
        if prefix not in spans:
            raise GateError(f"mutant function span missing: {path} {name}")
        start, end = spans[prefix]
        if method == "name_fallback":
            fan = list(selection)
        else:
            fan = [t for t in selection if any(start <= n <= end for n in executed.get(t, ()))]
        function_cost[prefix] = C_MUTANT_MS + sum(seconds[t] for t in fan)
    work = sum(function_cost[mutant_prefix(n)] for n in gated_names)
    return {
        "function_cost_ms": function_cost,
        "W_F_ms": work,
        "fixed_est_ms": STATS_PASSES * sum(seconds.values()),
        "cost_ms": work // len(gated_names) if gated_names else 0,
    }


# ---------------------------------------------------------------------------
# Partition (TD 5.20.5)
# ---------------------------------------------------------------------------


def partition(
    weights: Mapping[str, Mapping[str, int]], names_by_file: Mapping[str, Sequence[str]], count: int
) -> list[dict[str, Any]]:
    """Cut the sorted mutant sequence into `count` contiguous chunks of about equal weight.

    Each mutant goes to shard k; afterwards, while `k < count`, k advances once the running
    total reaches k/count of the whole. N is never adjusted and no mutant is split, so a
    trailing shard can be empty. The function reads no clock, environment or file.
    """
    sequence = [
        (path, name) for path in sorted(names_by_file) for name in sorted(names_by_file[path])
    ]
    total = sum(weights[path][name] for path, name in sequence)
    shards: list[dict[str, Any]] = [
        {"index": k, "members": {}, "est_mutation_ms": 0} for k in range(1, count + 1)
    ]
    k = 1
    cumulative = 0
    for path, name in sequence:
        weight = weights[path][name]
        shard = shards[k - 1]
        shard["members"].setdefault(path, []).append(name)
        shard["est_mutation_ms"] += weight
        cumulative += weight
        if k < count and cumulative * count >= k * total:
            k += 1
    return [
        {
            "index": s["index"],
            "members": [{"path": p, "names": s["members"][p]} for p in sorted(s["members"])],
            "est_mutation_ms": s["est_mutation_ms"],
        }
        for s in shards
    ]


def layout(files: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """W, N and the assignment, recomputed from the plan's stored per-function weights (SH-7b).

    The plan step and the merge both call this, so the merge can require a plan's N and
    assignment to equal exactly what this code produces from the plan's own numbers.
    """
    weights: dict[str, dict[str, int]] = {}
    names: dict[str, list[str]] = {}
    fixed: dict[str, int] = {}
    for rec in files:
        if not rec["to_shards"]:
            continue
        path = rec["path"]
        names[path] = sorted(rec["gated_mutant_names"])
        fixed[path] = rec["fixed_est_ms"]
        weights[path] = {}
        for name in names[path]:
            prefix = mutant_prefix(name)
            if prefix not in rec["function_cost_ms"]:
                raise GateError(f"plan lacks a function cost for {path} {name}")
            weights[path][name] = rec["function_cost_ms"][prefix]
    by_file = {path: sum(w.values()) for path, w in weights.items()}
    total = sum(by_file.values())
    count, capped = shard_count(total)
    assignment = []
    for part in partition(weights, names, count):
        est_fixed = sum(fixed[m["path"]] for m in part["members"])
        assignment.append({**part, "est_fixed_ms": est_fixed})
    return {
        "W_ms": total,
        "N": count,
        "capped": capped,
        "assignment": assignment,
        "W_F_ms": by_file,
    }


def ci_minutes(work_ms: int) -> float:
    """CI-minutes of work, one decimal: a display value only."""
    return round(work_ms / (CI_CORES * MS_PER_MINUTE), 1)


def plan_constants() -> dict[str, Any]:
    return {
        "T_MS": T_MS,
        "N_MAX": N_MAX,
        "CI_CORES": CI_CORES,
        "C_MUTANT_MS": C_MUTANT_MS,
        "D_DEFAULT_MS": D_DEFAULT_MS,
        "D_CLAMP_MS": D_CLAMP_MS,
        "STATS_PASSES": STATS_PASSES,
        "COST_MODEL": COST_MODEL,
        "BUDGET_SECONDS": ncg.BUDGET_SECONDS,
        "PLAN_BUDGET_SECONDS": ncg.PLAN_BUDGET_SECONDS,
    }


# ---------------------------------------------------------------------------
# Hashes (TD 5.20.6, 5.20.8)
# ---------------------------------------------------------------------------


def document_hash(doc: Mapping[str, Any], own_key: str) -> str:
    """sha256 of a plan or fragment minus its own hash field (top level only) and timing keys."""

    def strip(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in DOCUMENT_HASH_DROPS}
        if isinstance(value, list):
            return [strip(v) for v in value]
        return value

    body = strip({k: v for k, v in doc.items() if k != own_key})
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


def plan_hash(plan: Mapping[str, Any]) -> str:
    return document_hash(plan, "plan_hash")


def fragment_hash(fragment: Mapping[str, Any]) -> str:
    return document_hash(fragment, "fragment_sha256")


# ---------------------------------------------------------------------------
# Shape checks on untrusted documents
# ---------------------------------------------------------------------------


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_count(value: Any) -> bool:
    return _is_int(value) and value >= 0


def _is_number_or_none(value: Any) -> bool:
    return value is None or (isinstance(value, (int, float)) and not isinstance(value, bool))


def _is_str_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _is_count_map(value: Any) -> bool:
    return isinstance(value, dict) and all(
        isinstance(k, str) and _is_count(v) for k, v in value.items()
    )


def _is_reason_list(value: Any, codes: Iterable[str]) -> bool:
    allowed = set(codes)
    return isinstance(value, list) and all(
        isinstance(r, dict) and r.get("code") in allowed and isinstance(r.get("message"), str)
        for r in value
    )


def _assignment_error(assignment: Any) -> str | None:
    if not isinstance(assignment, list):
        return "assignment is not a list"
    for shard in assignment:
        ok = (
            isinstance(shard, dict)
            and _is_count(shard.get("index"))
            and _is_count(shard.get("est_mutation_ms"))
            and _is_count(shard.get("est_fixed_ms"))
            and isinstance(shard.get("members"), list)
            and all(
                isinstance(m, dict)
                and isinstance(m.get("path"), str)
                and _is_str_list(m.get("names"))
                for m in shard["members"]
            )
        )
        if not ok:
            return "assignment entry has the wrong shape"
    return None


def _plan_file_error(rec: Any) -> str | None:
    if not isinstance(rec, dict):
        return "a plan file entry is not an object"
    missing = sorted((set(ncg.FILE_FIELDS) | set(PLAN_FILE_EXTRA)) - set(rec))
    if missing:
        return f"a plan file entry lacks {', '.join(missing)}"
    ok = (
        isinstance(rec["path"], str)
        and isinstance(rec["to_shards"], bool)
        and _is_str_list(rec["gated_mutant_names"])
        and len(set(rec["gated_mutant_names"])) == len(rec["gated_mutant_names"])
        and _is_count_map(rec["function_cost_ms"])
        and _is_count(rec["fixed_est_ms"])
        and _is_count(rec["W_F_ms"])
        and _is_reason_list(rec["fail_reasons"], ncg.FAIL_ORDER)
    )
    return None if ok else "a plan file entry has the wrong shape"


def plan_shape_error(plan: Any) -> str | None:
    """Why `plan` cannot be read as a plan document, or None. Nothing here trusts a value's type."""
    if not isinstance(plan, dict):
        return "plan is not an object"
    if plan.get("schema") != ncg.SCHEMA_PLAN:
        return "plan has the wrong schema"
    basics = (
        isinstance(plan.get("binding"), dict)
        and isinstance(plan.get("files"), list)
        and isinstance(plan.get("internal_errors"), list)
        and isinstance(plan.get("plan_hash"), str)
        and isinstance(plan.get("capped"), bool)
        and _is_count(plan.get("W_ms"))
        and _is_int(plan.get("N"))
        and 1 <= plan["N"] <= N_MAX
        and isinstance(plan.get("tool_versions"), dict)
        and isinstance(plan.get("python"), str)
        and _is_number_or_none(plan.get("seconds"))
        and _is_number_or_none(plan.get("job_seconds"))
    )
    if not basics:
        return "plan is missing a field or has one of the wrong type"
    if not all(isinstance(e, dict) for e in plan["internal_errors"]):
        return "plan internal_errors holds a non-object"
    for rec in plan["files"]:
        error = _plan_file_error(rec)
        if error is not None:
            return error
    return _assignment_error(plan.get("assignment"))


def _finding_ok(finding: Any) -> bool:
    return isinstance(finding, dict) and all(isinstance(finding.get(k), str) for k in FINDING_KEYS)


def _isolation_ok(value: Any) -> bool:
    return value is None or (
        isinstance(value, dict)
        and isinstance(value.get("stage"), str)
        and _is_str_list(value.get("node_ids"))
        and _is_str_list(value.get("summary_lines"))
        and isinstance(value.get("output_tail"), str)
    )


def _status_map_ok(value: Any) -> bool:
    return isinstance(value, dict) and all(
        ncg.check_mutant_key(k) and isinstance(v, str) and v in MUTANT_STATUSES
        for k, v in value.items()
    )


def _fragment_entry_ok(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("path"), str)
        and _is_count(entry.get("assigned"))
        and _status_map_ok(entry.get("status_by_key"))
        and _is_count(entry.get("killed"))
        and _is_count(entry.get("total"))
        and _is_count_map(entry.get("mutant_status_counts"))
        and _is_reason_list(entry.get("fail_reasons"), SHARD_FAIL_CODES)
        and (entry.get("mutation_reason") is None or isinstance(entry["mutation_reason"], str))
        and entry.get("mutation_reason") in SHARD_REASONS
        and isinstance(entry.get("path_load_findings"), list)
        and all(_finding_ok(f) for f in entry["path_load_findings"])
        and _isolation_ok(entry.get("isolation_failure"))
        and all(
            isinstance(entry.get(k), (int, float)) and not isinstance(entry.get(k), bool)
            for k in ("workspace_seconds", "mutmut_seconds", "collect_seconds", "seconds")
        )
        and isinstance(entry.get("finished"), bool)
    )


def _timeout_ok(value: Any) -> bool:
    return value is None or (
        isinstance(value, dict)
        and all(isinstance(value.get(k), str) for k in ("phase", "file", "message"))
    )


def fragment_shape_error(doc: Any) -> str | None:
    """Why `doc` cannot be read as a fragment, or None."""
    if not isinstance(doc, dict):
        return "fragment is not an object"
    if doc.get("schema") != ncg.SCHEMA_FRAGMENT:
        return "fragment has the wrong schema"
    ok = (
        isinstance(doc.get("binding"), dict)
        and doc.get("status") in SHARD_STATUSES
        and _timeout_ok(doc.get("timeout"))
        and isinstance(doc.get("internal_errors"), list)
        and all(isinstance(e, dict) for e in doc["internal_errors"])
        and isinstance(doc.get("files"), list)
        and isinstance(doc.get("fragment_sha256"), str)
        and _is_number_or_none(doc.get("seconds"))
        and _is_number_or_none(doc.get("job_seconds"))
    )
    if not ok:
        return "fragment is missing a field or has one of the wrong type"
    if not all(_fragment_entry_ok(e) for e in doc["files"]):
        return "a fragment file entry has the wrong shape"
    paths = [e["path"] for e in doc["files"]]
    if len(set(paths)) != len(paths):
        return "a fragment lists a file twice"
    return None


# ---------------------------------------------------------------------------
# Merge (TD 5.20.9)
# ---------------------------------------------------------------------------


def problem(
    code: str, message: str, shard: int | None = None, file: str | None = None
) -> dict[str, Any]:
    """One `internal_errors` entry of the merge: `{code, message, shard?, file?}`."""
    entry: dict[str, Any] = {
        "code": code,
        "message": ncg.bound_text(message, ncg.MAX_MESSAGE_CHARS),
    }
    if shard is not None:
        entry["shard"] = shard
    if file is not None:
        entry["file"] = ncg.bound_text(file, ncg.MAX_PATH_CHARS)
    return entry


def _shown(value: Any) -> str:
    return ncg.bound_text(str(value), ncg.MAX_PATH_CHARS)


def plan_consistency_error(plan: Mapping[str, Any]) -> str | None:
    """The plan must equal what `layout` produces from its own stored weights (SH-7b, C9)."""
    try:
        lay = layout(plan["files"])
    except GateError as exc:
        return str(exc)
    if lay["N"] != plan["N"]:
        return f"plan N is {plan['N']} but its own weights give {lay['N']}"
    if lay["W_ms"] != plan["W_ms"] or lay["capped"] != plan["capped"]:
        return "plan W_ms or capped differs from its own weights"
    for rec in plan["files"]:
        if rec["to_shards"] and rec["W_F_ms"] != lay["W_F_ms"][rec["path"]]:
            return f"plan W_F_ms for {_shown(rec['path'])} differs from its own weights"
    if lay["assignment"] != plan["assignment"]:
        return "plan assignment is not the partition this code produces from its weights"
    return None


def plan_problems(
    plan: Any, plan_result: str, binding: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], bool]:
    """Every problem with the plan, and whether it can still be read to look at the fragments."""
    found = []
    if plan_result != "success":
        found.append(problem("plan_not_successful", f"plan job result {_shown(plan_result)}"))
    error = plan_shape_error(plan)
    if error is not None:
        found.append(problem("plan_unreadable", error))
        return found, False
    if plan["plan_hash"] != plan_hash(plan):
        found.append(problem("plan_hash_mismatch", "plan_hash does not match the plan's content"))
    inconsistent = plan_consistency_error(plan)
    if inconsistent is not None:
        found.append(problem("plan_inconsistent", inconsistent))
    unbound = ncg.check_records_binding(
        plan["binding"],
        binding["mode"],
        binding["gated_sha"],
        binding["pr"],
        binding["run_id"],
        binding["run_attempt"],
    )
    if unbound is not None:
        found.append(problem("plan_not_bound", unbound))
    for entry in plan["internal_errors"]:
        found.append(problem("plan_internal_error", f"{entry.get('code')}: {entry.get('message')}"))
    return found, True


def index_fragments(
    fragments: Mapping[str, Any], count: int
) -> tuple[dict[int, str], list[dict[str, Any]]]:
    """Map each shard index to its one fragment directory, and report every structural problem."""
    by_index: dict[int, list[str]] = {}
    found = []
    for name in sorted(fragments):
        match = FRAGMENT_NAME_RE.match(name)
        if match is None:
            found.append(problem("fragment_extra", f"unexpected entry: {_shown(name)}"))
        elif isinstance(fragments[name], str):
            found.append(problem("fragment_extra", f"{_shown(name)}: {fragments[name]}"))
        elif int(match[2]) != count:
            found.append(
                problem("fragment_extra", f"{_shown(name)} is not for this plan's {count} shards")
            )
        elif not 1 <= int(match[1]) <= count:
            found.append(
                problem(
                    "fragment_out_of_range", f"{_shown(name)}: shard index is not in 1..{count}"
                )
            )
        else:
            by_index.setdefault(int(match[1]), []).append(name)
    names: dict[int, str] = {}
    for index, entries in sorted(by_index.items()):
        if len(entries) > 1:
            listed = ", ".join(_shown(e) for e in entries)
            found.append(
                problem(
                    "fragment_duplicate",
                    f"shard {index} of {count} has {len(entries)} fragments: {listed}",
                    index,
                )
            )
        else:
            names[index] = entries[0]
    return names, found


def _attempt_problem(value: Any, plan_attempt: Any, current: int | None) -> str | None:
    if current is None:
        return None if value is None else "run_attempt is set but this run has none"
    floor = ncg.attempt_number(plan_attempt) or 0
    if not _is_int(value) or not floor <= value <= current:
        return f"run_attempt {_shown(value)} is not an integer from {floor} to {current}"
    return None


def fragment_problems(
    doc: Any, index: int, name: str, plan: Mapping[str, Any], binding: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Why a fragment cannot count for shard `index`: unreadable, forged, stale, another run."""
    count = plan["N"]
    where = f"shard {index} of {count}"
    error = fragment_shape_error(doc)
    if error is not None:
        return [problem("fragment_unreadable", f"{where}: {error}", index)]
    found = []
    if doc["fragment_sha256"] != fragment_hash(doc):
        found.append(
            problem("fragment_hash_mismatch", f"{where}: fragment_sha256 does not match", index)
        )
    bound = doc["binding"]
    plan_binding = plan["binding"]
    expected = {
        "gated_sha": plan_binding.get("gated_sha"),
        "pr": plan_binding.get("pr"),
        "run_id": plan_binding.get("run_id"),
        "N": count,
        "plan_hash": plan["plan_hash"],
    }
    differing = [k for k, want in expected.items() if bound.get(k) != want]
    if differing:
        found.append(
            problem(
                "fragment_not_bound",
                f"{where}: {', '.join(differing)} differ from the plan's",
                index,
            )
        )
    if bound.get("index") != index:
        found.append(
            problem(
                "fragment_name_mismatch",
                f"{where}: {_shown(name)} holds index {_shown(bound.get('index'))}",
                index,
            )
        )
    attempt = _attempt_problem(
        bound.get("run_attempt"), plan_binding.get("run_attempt"), binding["run_attempt"]
    )
    if attempt is not None:
        found.append(problem("fragment_attempt", f"{where}: {attempt}", index))
    return found


def _assigned(plan: Mapping[str, Any]) -> dict[int, dict[str, list[str]]]:
    return {
        s["index"]: {m["path"]: list(m["names"]) for m in s["members"]} for s in plan["assignment"]
    }


def result_problems(
    usable: Mapping[int, Mapping[str, Any]], assigned: Mapping[int, Mapping[str, list[str]]]
) -> list[dict[str, Any]]:
    """REQ-40: every planned mutant has one result, in the fragment of its assigned shard."""
    found = []
    seen: dict[tuple[str, str], int] = {}
    for index, doc in sorted(usable.items()):
        mine = assigned.get(index, {})
        for entry in doc["files"]:
            path = entry["path"]
            for key in sorted(entry["status_by_key"]):
                if (path, key) in seen:
                    found.append(
                        problem(
                            "mutant_in_two_fragments",
                            f"shard {index}: {_shown(key)} also has a result in shard "
                            f"{seen[(path, key)]}",
                            index,
                            path,
                        )
                    )
                seen.setdefault((path, key), index)
                if key not in mine.get(path, ()):
                    found.append(
                        problem(
                            "mutant_in_wrong_fragment",
                            f"shard {index}: {_shown(key)} was not assigned to this shard",
                            index,
                            path,
                        )
                    )
        if doc["status"] == "complete":
            found.extend(_missing_results(index, doc, mine))
    return found


def _missing_results(
    index: int, doc: Mapping[str, Any], mine: Mapping[str, list[str]]
) -> list[dict[str, Any]]:
    entries = {e["path"]: e for e in doc["files"]}
    found = []
    for path in sorted(mine):
        entry = entries.get(path)
        if entry is not None and entry["fail_reasons"]:
            continue
        have = set(entry["status_by_key"]) if entry is not None and entry["finished"] else set()
        lacking = [n for n in mine[path] if n not in have]
        if not lacking and entry is not None and entry["finished"]:
            counted = ncg.classify_statuses(entry["status_by_key"], mine[path])
            stated = (entry["killed"], entry["total"], entry["mutant_status_counts"])
            if stated != (
                counted["mutants_killed"],
                counted["mutants_total"],
                counted["mutant_status_counts"],
            ):
                found.append(
                    problem(
                        "fragment_count_mismatch",
                        f"shard {index} states killed/total {stated[0]}/{stated[1]}, its mutant "
                        f"statuses give {counted['mutants_killed']}/{counted['mutants_total']}",
                        index,
                        path,
                    )
                )
        if lacking:
            found.append(
                problem(
                    "planned_mutant_without_result",
                    f"shard {index} has no result for {len(lacking)} planned mutant(s), "
                    f"first {_shown(lacking[0])}",
                    index,
                    path,
                )
            )
    return found


def _internal_problems(index: int, doc: Mapping[str, Any]) -> list[dict[str, Any]]:
    if doc["status"] != "internal_error":
        return []
    found = []
    for entry in doc["internal_errors"] or [{}]:
        text = f"{entry.get('code', 'internal_error')}: {entry.get('message', 'no detail')}"
        file = entry.get("file")
        found.append(
            problem(
                "shard_internal_error",
                f"shard {index}: {text}",
                index,
                file if isinstance(file, str) else None,
            )
        )
    return found


def _clean_finding(finding: Mapping[str, Any]) -> dict[str, str]:
    return {k: ncg.bound_text(finding[k], ncg.MAX_PATH_CHARS) for k in FINDING_KEYS}


def _clean_isolation(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "stage": ncg.bound_text(value["stage"], ncg.MAX_PATH_CHARS),
        "node_ids": [ncg.bound_text(n, ncg.MAX_NODE_ID_CHARS) for n in value["node_ids"]],
        "summary_lines": [
            ncg.bound_text(s, ncg.MAX_SUMMARY_LINE_CHARS)
            for s in value["summary_lines"][: ncg.MAX_SUMMARY_LINES]
        ],
        "output_tail": ncg.bound_text(value["output_tail"], ncg.ISOLATION_TAIL_CHARS),
    }


def timeout_text(
    index: int, count: int, timeout: Mapping[str, Any] | None, paths: Sequence[str]
) -> str:
    """The `mutation_timeout` message for one overrunning shard (TD 5.20.10)."""
    where = ""
    if timeout is not None and timeout["phase"]:
        where = f" (ran out in {timeout['phase']}" + (
            f" of {timeout['file']})" if timeout["file"] else ")"
        )
    return (
        f"shard {index} of {count} overran its {ncg.BUDGET_SECONDS // 60}-minute budget{where}; "
        f"files with mutants in shard {index}: {', '.join(paths)}; split the PR"
    )


class FileMerge:
    """The merge of one `to_shards` file: its holders' entries, final or not, and the reasons."""

    def __init__(
        self,
        rec: Mapping[str, Any],
        holders: Sequence[int],
        usable: Mapping[int, Mapping[str, Any]],
        states: Mapping[int, str],
    ) -> None:
        self.rec = rec
        self.holders = list(holders)
        self.docs = {i: usable[i] for i in holders if i in usable}
        self.entries = {
            i: next((e for e in d["files"] if e["path"] == rec["path"]), None)
            for i, d in self.docs.items()
        }
        self.states = states

    def row(self, index: int) -> dict[str, Any]:
        entry = self.entries.get(index)
        status = (
            self.docs[index]["status"] if index in self.docs else self.states.get(index, "missing")
        )
        return {
            "index": index,
            "killed": entry["killed"] if entry is not None else None,
            "total": entry["total"] if entry is not None else None,
            "status": status,
        }

    def timed_out(self) -> list[int]:
        return [i for i in self.holders if i in self.docs and self.docs[i]["status"] == "timeout"]

    def is_final(self) -> bool:
        return all(
            i in self.docs
            and self.docs[i]["status"] == "complete"
            and self.entries[i] is not None
            and not self.entries[i]["fail_reasons"]
            for i in self.holders
        )


def _shard_reasons(fm: FileMerge) -> list[dict[str, str]]:
    found = []
    for index in fm.holders:
        entry = fm.entries.get(index)
        if entry is not None and fm.docs[index]["status"] == "complete":
            found.extend(
                {"code": r["code"], "message": ncg.bound_text(r["message"], ncg.MAX_MESSAGE_CHARS)}
                for r in entry["fail_reasons"]
            )
    return found


def _not_final(
    out: dict[str, Any], fm: FileMerge, count: int, assigned: Mapping[int, Mapping[str, list[str]]]
) -> None:
    out.update(
        mutation_ran=False,
        mutants_killed=None,
        mutants_total=None,
        mutant_score_pct=None,
        mutant_status_counts={},
    )
    reasons = list(out["fail_reasons"])
    late = fm.timed_out()
    if late:
        message = " ".join(
            timeout_text(i, count, fm.docs[i]["timeout"], sorted(assigned[i])) for i in late
        )
        reasons.append(
            ncg.fail_reason("mutation_timeout", ncg.bound_text(message, ncg.MAX_MESSAGE_CHARS))
        )
        reasons.extend(_shard_reasons(fm))
        out["mutation_reason"] = "timeout"
    else:
        reasons.extend(_shard_reasons(fm))
        first = next(
            (
                fm.entries[i]
                for i in fm.holders
                if fm.entries.get(i) and fm.entries[i]["mutation_reason"]
            ),
            None,
        )
        out["mutation_reason"] = first["mutation_reason"] if first is not None else "internal_error"
        found = next(
            (
                fm.entries[i]
                for i in fm.holders
                if fm.entries.get(i) and fm.entries[i]["path_load_findings"]
            ),
            None,
        )
        if found is not None:
            out["path_load_findings"] = [
                _clean_finding(f) for f in found["path_load_findings"][:MAX_FINDINGS]
            ]
        failure = next(
            (
                fm.entries[i]
                for i in fm.holders
                if fm.entries.get(i) and fm.entries[i]["isolation_failure"]
            ),
            None,
        )
        if failure is not None:
            out["isolation_failure"] = _clean_isolation(failure["isolation_failure"])
    out["fail_reasons"] = ncg.ordered_reasons(reasons)


def _final(out: dict[str, Any], fm: FileMerge, problems: list[dict[str, Any]]) -> None:
    killed = 0
    total = 0
    counts: dict[str, int] = {}
    for index in fm.holders:
        statuses = fm.entries[index]["status_by_key"]
        shard = ncg.classify_statuses(statuses, statuses)
        killed += shard["mutants_killed"]
        total += shard["mutants_total"]
        for status, number in shard["mutant_status_counts"].items():
            counts[status] = counts.get(status, 0) + number
    if total != len(fm.rec["gated_mutant_names"]):
        problems.append(
            problem(
                "planned_mutant_without_result",
                f"shards report {total} mutants, the plan has "
                f"{len(fm.rec['gated_mutant_names'])}",
                None,
                out["path"],
            )
        )
    out.update(
        mutation_ran=True,
        mutation_reason=None,
        mutants_killed=killed,
        mutants_total=total,
        mutant_score_pct=ncg.mutant_score_pct(killed, total),
        mutant_status_counts=dict(sorted(counts.items())),
    )


def merge_file(
    rec: Mapping[str, Any],
    plan: Mapping[str, Any],
    usable: Mapping[int, Mapping[str, Any]],
    states: Mapping[int, str],
    problems: list[dict[str, Any]],
) -> dict[str, Any]:
    """One plan file as a final record: score summed over its shards, or not final (REQ-41/42)."""
    out = {k: v for k, v in rec.items() if k not in PLAN_FILE_EXTRA}
    out["plan_hash"] = plan["plan_hash"]
    out["N"] = plan["N"]
    out["shards"] = []
    if not rec["to_shards"]:
        return out
    assigned = _assigned(plan)
    holders = sorted(i for i, held in assigned.items() if rec["path"] in held)
    fm = FileMerge(rec, holders, usable, states)
    out["shards"] = [fm.row(i) for i in holders]
    if fm.is_final():
        _final(out, fm, problems)
    else:
        _not_final(out, fm, plan["N"], assigned)
    for entry in (e for e in fm.entries.values() if e is not None):
        for name in ("workspace_seconds", "mutmut_seconds", "collect_seconds", "seconds"):
            out[name] = round(out[name] + entry[name], 3)
    return out


def shard_summary(
    plan: Mapping[str, Any], states: Mapping[int, str], usable: Mapping[int, Mapping[str, Any]]
) -> dict[str, Any]:
    per_shard = []
    for shard in plan["assignment"]:
        index = shard["index"]
        doc = usable.get(index)
        per_shard.append(
            {
                "index": index,
                "status": doc["status"] if doc is not None else states.get(index, "missing"),
                "run_attempt": doc["binding"].get("run_attempt") if doc is not None else None,
                "seconds": doc.get("seconds") if doc is not None else None,
                "job_seconds": doc.get("job_seconds") if doc is not None else None,
                "files": [m["path"] for m in shard["members"]],
                "est_mutation_ms": shard["est_mutation_ms"],
                "est_fixed_ms": shard["est_fixed_ms"],
                "fragment_sha256": doc["fragment_sha256"] if doc is not None else None,
            }
        )
    return {
        "N": plan["N"],
        "capped": plan["capped"],
        "W_ms": plan["W_ms"],
        "W_ci_minutes": ci_minutes(plan["W_ms"]),
        "T_minutes": T_MS // MS_PER_MINUTE,
        "N_max": N_MAX,
        "plan_hash": plan["plan_hash"],
        "per_shard": per_shard,
    }


def runner_minutes_total(records: Mapping[str, Any], gate_seconds: float) -> float | None:
    """(plan + shard job seconds + the gate's own seconds) / 60, or None if any is unknown."""
    shards = records.get("shards")
    terms = [records.get("plan_job_seconds"), gate_seconds]
    if isinstance(shards, dict):
        terms.extend(s["job_seconds"] for s in shards["per_shard"])
    if any(t is None for t in terms):
        return None
    return round(sum(terms) / 60, 1)


def skeleton(plan: Mapping[str, Any] | None, binding: Mapping[str, Any]) -> dict[str, Any]:
    """The top level of the merged records, with the plan's values when there is a readable plan."""
    given = plan["binding"] if plan is not None else {}
    return {
        "schema": ncg.SCHEMA_RECORDS,
        "gate_version": ncg.GATE_VERSION,
        "phase": "merge",
        "mode": binding["mode"],
        "pr": binding["pr"],
        "gated_sha": binding["gated_sha"],
        "pr_head_sha": given.get("pr_head_sha"),
        "base_sha": given.get("base_sha"),
        "gated_tree": given.get("gated_tree"),
        "run_id": binding["run_id"],
        "run_attempt": binding["run_attempt"],
        "tool_versions": plan["tool_versions"] if plan is not None else {},
        "python": plan["python"] if plan is not None else None,
        "coverage_core": plan.get("coverage_core") if plan is not None else None,
        "budget_seconds": ncg.BUDGET_SECONDS,
        "thresholds": dict(ncg.THRESHOLDS),
        "plan_hash": plan["plan_hash"] if plan is not None else None,
        "plan_seconds": plan.get("seconds") if plan is not None else None,
        "plan_job_seconds": plan.get("job_seconds") if plan is not None else None,
        "merge_verdict_seconds": None,
        "runner_minutes_total": None,
    }


def merge(
    plan: Any,
    fragments: Mapping[str, Any],
    plan_result: str,
    shard_result: str,
    binding: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Plan plus fragments in, the merged records and EVERY problem out (REQ-40 to REQ-42).

    `fragments` maps a directory name to its parsed document, to None when it could not be
    parsed, or to a message when the entry is not a directory holding exactly one regular file.
    A problem makes the caller's result exit 3; the records are still built, for display.
    """
    problems, readable = plan_problems(plan, plan_result, binding)
    records = skeleton(plan if readable else None, binding)
    if not readable:
        records.update(files=[], shards=None)
        return _finish(records, problems, shard_result)
    count = plan["N"]
    if plan_result != "success":
        fragments = {}
    names, structural = index_fragments(fragments, count)
    problems.extend(structural)
    usable: dict[int, Mapping[str, Any]] = {}
    states = {i: "missing" for i in range(1, count + 1)}
    for index, name in names.items():
        found = fragment_problems(fragments[name], index, name, plan, binding)
        states[index] = "invalid"
        if found:
            problems.extend(found)
        else:
            usable[index] = fragments[name]
    for index in range(1, count + 1):
        if plan_result != "success":
            break
        if index not in names and not any(p.get("shard") == index for p in problems):
            problems.append(
                problem("fragment_missing", f"shard {index} of {count}: no fragment", index)
            )
    problems.extend(result_problems(usable, _assigned(plan)))
    for index, doc in sorted(usable.items()):
        problems.extend(_internal_problems(index, doc))
    records["files"] = sorted(
        (merge_file(rec, plan, usable, states, problems) for rec in plan["files"]),
        key=lambda r: r["path"],
    )
    records["shards"] = shard_summary(plan, states, usable)
    return _finish(records, problems, shard_result)


def _finish(
    records: dict[str, Any], problems: list[dict[str, Any]], shard_result: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if shard_result != "success":
        named = sorted({p["shard"] for p in problems if p.get("shard") is not None})
        detail = (
            f"shard(s) {', '.join(map(str, named))}"
            if named
            else "no fragment identifies the failing shard"
        )
        problems.append(
            problem(
                "shard_job_not_successful", f"shard job result {_shown(shard_result)}; {detail}"
            )
        )
    records["internal_errors"] = problems
    records["records_sha256"] = ncg.records_sha256(records["files"])
    return records, problems


# ---------------------------------------------------------------------------
# A fragment on its own (`run --only-shard`)
# ---------------------------------------------------------------------------


def fragment_summary(fragment: Mapping[str, Any]) -> str:
    """The text of one shard's result, for the partial local run that never decides (REQ-3)."""
    binding = fragment["binding"]
    lines = [f"shard {binding['index']} of {binding['N']}: {fragment['status']}"]
    for entry in fragment["files"]:
        lines.append(
            f"- {entry['path']}: {entry['killed']}/{entry['total']} killed of "
            f"{entry['assigned']} assigned"
            + ("" if entry["finished"] else " (not finished)")
            + "".join(f"; {r['code']}" for r in entry["fail_reasons"])
        )
    lines.extend(f"- {e.get('code')}: {e.get('message')}" for e in fragment["internal_errors"])
    return "\n".join(lines) + "\n"
