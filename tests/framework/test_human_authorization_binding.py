"""Tests for human_authorization.compute_binding (TD-2101 §7.3, T-B-*).

Real git in pytest tmp_path repos; no network. Every repo is built with an
isolated environment so the developer's own git config cannot leak in."""

from __future__ import annotations

import ast
import math
import os
import subprocess
from pathlib import Path

import pytest

from scripts.framework import human_authorization as ha
from scripts.framework.human_authorization import VerifierError, compute_binding

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # pragma: allowlist secret


def _env(home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        HOME=str(home),
        GIT_CONFIG_GLOBAL="/dev/null",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
        GIT_AUTHOR_DATE="2026-01-01T00:00:00Z",
        GIT_COMMITTER_DATE="2026-01-01T00:00:00Z",
    )
    return env


def git(repo: Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        env=_env(repo.parent),
        check=False,
    )
    if check and r.returncode != 0:
        raise AssertionError(f"git {args} failed: {r.stderr}")
    return r.stdout.strip()


def write(repo: Path, rel: str, content: str | bytes) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        p.write_bytes(content)
    else:
        p.write_text(content)


def commit(repo: Path, msg: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


def init(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "base.txt", "base\n")
    commit(repo, "base")
    return repo


def step_branch(repo: Path) -> str:
    """main + one step commit on branch `step`; returns head sha."""
    git(repo, "checkout", "-q", "-b", "step")
    write(repo, "scripts/x.py", "print('x')\n")
    write(repo, "docs/y.md", "# y\n")
    return commit(repo, "step")


def test_t_b_1_binding_form_and_sorted_files(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    b = compute_binding(repo, "main", head)
    assert ha.BINDING_RE.match(b.binding)
    assert b.diff_files == ("docs/y.md", "scripts/x.py")
    assert b.head_sha == head
    assert b.base_sha == git(repo, "rev-parse", "main")
    assert b.merge_base == b.base_sha


def test_t_b_1_rename_lists_both_paths(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "step")
    git(repo, "mv", "base.txt", "renamed.txt")
    head = commit(repo, "rename")
    assert compute_binding(repo, "main", head).diff_files == ("base.txt", "renamed.txt")


def test_t_b_2_clean_merge_from_base_keeps_binding(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    before = compute_binding(repo, "main", head)
    git(repo, "checkout", "-q", "main")
    write(repo, "unrelated.txt", "u\n")
    commit(repo, "main moves")
    git(repo, "checkout", "-q", "step")
    git(repo, "merge", "-q", "--no-edit", "main")
    merged = git(repo, "rev-parse", "HEAD")
    assert merged != head
    after = compute_binding(repo, "main", merged)
    assert after.binding == before.binding
    assert after.diff_files == before.diff_files


def test_t_b_3_new_step_commit_changes_binding(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    first = compute_binding(repo, "main", head)
    write(repo, "scripts/x.py", "print('x2')\n")
    head2 = commit(repo, "more")
    assert compute_binding(repo, "main", head2).binding != first.binding


def test_t_b_4_whitespace_only_commit_changes_binding(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    first = compute_binding(repo, "main", head)
    write(repo, "scripts/x.py", "print('x') \n")
    head2 = commit(repo, "ws")
    assert compute_binding(repo, "main", head2).binding != first.binding


def test_t_b_5_hostile_config_and_env_do_not_change_the_id(tmp_path, monkeypatch):
    repo = init(tmp_path)
    sentinel = tmp_path / "SENTINEL"
    git(repo, "checkout", "-q", "-b", "step")
    body = "".join(f"line {i}\n" for i in range(30))
    write(repo, "a.py", body)
    write(repo, ".gitattributes", "*.py diff=evil\n")
    commit(repo, "files")
    write(repo, "a.py", body.replace("line 15", "line fifteen"))
    head = commit(repo, "edit")
    clean = compute_binding(repo, "main", head).binding

    home = tmp_path / "hostile-home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[diff]\n algorithm = patience\n renames = copies\n noprefix = true\n context = 10\n"
        ' mnemonicPrefix = true\n[diff "evil"]\n textconv = touch ' + str(sentinel) + "; cat\n"
        "[patchid]\n stable = false\n[core]\n quotePath = false\n"
    )
    for k, v in [
        ("diff.algorithm", "histogram"),
        ("diff.renames", "copies"),
        ("diff.context", "0"),
        ("diff.evil.textconv", f"touch {sentinel}; cat"),
        ("diff.evil.command", f"touch {sentinel}"),
    ]:
        git(repo, "config", "--local", k, v)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_PARAMETERS", "'diff.algorithm'='patience'")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "diff.context")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "0")
    monkeypatch.setenv("GIT_DIFF_OPTS", "--unified=0")
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", f"touch {sentinel}")
    assert compute_binding(repo, "main", head).binding == clean
    assert not sentinel.exists()


def _binary_repo(tmp_path: Path, name: str, payload: bytes, info_attrs: bool = False):
    repo = init(tmp_path, name)
    git(repo, "checkout", "-q", "-b", "step")
    write(repo, "blob.bin", payload)
    write(repo, "scripts/x.py", "x\n")
    head = commit(repo, "bin")
    if info_attrs:
        (repo / ".git" / "info").mkdir(exist_ok=True)
        (repo / ".git" / "info" / "attributes").write_text("* -diff\n")
    return repo, head


def test_t_b_6_binary_content_is_bound(tmp_path):
    p1, p2 = b"\x00\x01\x02" * 50, b"\x00\x09\x08" * 50
    r1, h1 = _binary_repo(tmp_path, "r1", p1)
    r2, h2 = _binary_repo(tmp_path, "r2", p2)
    assert compute_binding(r1, "main", h1).binding != compute_binding(r2, "main", h2).binding
    r3, h3 = _binary_repo(tmp_path, "r3", p1, info_attrs=True)
    r4, h4 = _binary_repo(tmp_path, "r4", p2, info_attrs=True)
    assert compute_binding(r3, "main", h3).binding != compute_binding(r4, "main", h4).binding


@pytest.mark.parametrize("attrs", ["* -diff\n", "* binary\n"])
def test_t_b_6a_working_tree_gitattributes_cannot_change_the_id(tmp_path, attrs):
    repo = init(tmp_path)
    head = step_branch(repo)
    clean = compute_binding(repo, "main", head).binding
    (repo / ".gitattributes").write_text(attrs)  # uncommitted
    assert compute_binding(repo, "main", head).binding == clean


def test_t_b_6a_step_that_adds_gitattributes_is_checkout_independent(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "step")
    write(repo, "scripts/x.py", "x\n")
    write(repo, ".gitattributes", "* -diff\n")
    head = commit(repo, "step adds attrs")
    on_head = compute_binding(repo, "main", head).binding
    git(repo, "checkout", "-q", "main")
    on_base = compute_binding(repo, "main", head).binding
    assert on_head == on_base


def test_t_b_7_argv_pins_every_git_call(tmp_path, monkeypatch):
    repo = init(tmp_path)
    head = step_branch(repo)
    seen: list[list[str]] = []
    real = subprocess.run

    def spy(argv, *a, **k):
        if argv and argv[0] == "git":
            seen.append(list(argv))
        return real(argv, *a, **k)

    monkeypatch.setattr(ha.subprocess, "run", spy)
    compute_binding(repo, "main", head)
    assert len(seen) >= 6
    subcommands = {"rev-parse", "cat-file", "merge-base", "diff", "patch-id"}
    for argv in seen:
        assert argv[3] == "--no-replace-objects", argv
        assert argv[4] == f"--attr-source={EMPTY_TREE}", argv
        sub_idx = min(argv.index(s) for s in subcommands if s in argv)
        assert argv.index(f"--attr-source={EMPTY_TREE}") < sub_idx
        assert "--text" not in argv and "-a" not in argv
    patch_call = next(a for a in seen if "--binary" in a)
    for flag in (
        "--no-ext-diff",
        "--no-textconv",
        "--no-color",
        "--no-renames",
        "--full-index",
        "--binary",
    ):
        assert flag in patch_call, flag
    pairs = {(patch_call[i], patch_call[i + 1]) for i in range(len(patch_call) - 1)}
    assert ("-c", "diff.algorithm=myers") in pairs and ("-c", "core.quotePath=true") in pairs
    assert any(a[a.index("patch-id") + 1] == "--verbatim" for a in seen if "patch-id" in a)


def test_git_env_is_stripped_of_git_variables(tmp_path, monkeypatch):
    repo = init(tmp_path)
    head = step_branch(repo)
    clean = compute_binding(repo, "main", head).binding
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "nowhere"))
    assert compute_binding(repo, "main", head).binding == clean


def test_t_b_8_missing_base_and_head(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "no-such-ref", head)
    assert e.value.code == "git-failure"
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", "f" * 40)
    assert e.value.code == "git-failure"


def test_t_b_8_shallow_clone_missing_history(tmp_path):
    src = init(tmp_path, "src")
    head = step_branch(src)
    write(src, "later.txt", "l\n")
    commit(src, "later")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", "--branch", "main", f"file://{src}", str(shallow)],
        check=True,
        capture_output=True,
        env=_env(tmp_path),
    )
    with pytest.raises(VerifierError) as e:
        compute_binding(shallow, "main", head)
    assert e.value.code == "git-failure"


def test_t_b_8_empty_diff(tmp_path):
    repo = init(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", head)
    assert e.value.code == "empty-diff"


def test_t_b_8_criss_cross_history_is_ambiguous(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "b1")
    write(repo, "one.txt", "1\n")
    commit(repo, "b1")
    git(repo, "checkout", "-q", "-b", "b2", "main")
    write(repo, "two.txt", "2\n")
    commit(repo, "b2")
    git(repo, "checkout", "-q", "-b", "m1", "b1")
    git(repo, "merge", "-q", "--no-edit", "b2")
    git(repo, "checkout", "-q", "-b", "m2", "b2")
    git(repo, "merge", "-q", "--no-edit", "b1")
    write(repo, "three.txt", "3\n")
    head = commit(repo, "after")
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "m1", head)
    assert e.value.code == "ambiguous-merge-base"


def test_t_b_9_tab_in_path_is_unrepresentable(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "step")
    write(repo, "a\tb.txt", "x\n")
    head = commit(repo, "tab")
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", head)
    assert e.value.code == "unrepresentable-path"


def test_t_b_9_non_utf8_path_is_unrepresentable(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "step")
    with open(os.fsencode(repo) + b"/\xff.txt", "wb") as fh:
        fh.write(b"x\n")
    head = commit(repo, "bytes")
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", head)
    assert e.value.code == "unrepresentable-path"


def test_t_b_10_bad_refs_rejected_before_git_runs(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ha, "_run_git", lambda *a, **k: calls.append(a) or b"")
    assert (
        ha.main(["binding", "--repo-root", str(tmp_path), "--base=--output=x", "--head", "a" * 40])
        == 2
    )
    assert (
        ha.main(["binding", "--repo-root", str(tmp_path), "--base", "main", "--head", "abc"]) == 2
    )
    assert (
        ha.main(["binding", "--repo-root", str(tmp_path), "--base", "main", "--head", "A" * 40])
        == 2
    )
    assert calls == []
    for bad_base, head in (("-x", "a" * 40), ("main", "abc")):
        with pytest.raises(ValueError):
            compute_binding(tmp_path, bad_base, head)
    assert calls == []


def test_replace_refs_cannot_substitute_the_authorized_commit(tmp_path):
    repo = init(tmp_path)
    git(repo, "checkout", "-q", "-b", "authorized")
    write(repo, "scripts/x.py", "print('authorized')\n")
    authorized = commit(repo, "authorized")
    git(repo, "checkout", "-q", "-b", "unauthorized", "main")
    write(repo, "scripts/x.py", "print('EVIL')\n")
    write(repo, "extra.py", "evil\n")
    unauthorized = commit(repo, "unauthorized")
    want_auth = compute_binding(repo, "main", authorized)
    want_unauth = compute_binding(repo, "main", unauthorized)
    assert want_auth.binding != want_unauth.binding
    git(repo, "replace", unauthorized, authorized)
    got = compute_binding(repo, "main", unauthorized)
    assert got.binding == want_unauth.binding != want_auth.binding
    assert got.diff_files == want_unauth.diff_files


def test_replace_objects_env_var_is_stripped_not_relied_on(tmp_path, monkeypatch):
    repo = init(tmp_path)
    head = step_branch(repo)
    clean = compute_binding(repo, "main", head).binding
    monkeypatch.setenv("GIT_NO_REPLACE_OBJECTS", "0")
    monkeypatch.setenv("GIT_REPLACE_REF_BASE", "refs/nothing/")
    assert compute_binding(repo, "main", head).binding == clean


# ---------------------------------------------------------------------------
# R-A6: the binding must be position-sound (TD-2101 §4.7 step 5a, §10.3)
# ---------------------------------------------------------------------------

_BODY = [
    "    x = 1",
    "    y = 2",
    "    z = 3",
    "    w = 4",
    "    allowed = False",
    "    a = 5",
    "    b = 6",
    "    c = 7",
    "    return allowed",
]


def _two_functions(
    first_allowed: str = "False", second_allowed: str = "False", filler: int = 0
) -> str:
    def body(allowed: str) -> str:
        return "\n".join(ln.replace("False", allowed) for ln in _BODY)

    out = (
        f"def preview_access(user):\n{body(first_allowed)}\n\n\n"
        f"def production_access(user):\n{body(second_allowed)}\n"
    )
    out += "".join(f"\n# filler {i}\n" for i in range(filler))
    return out


def _branch_from_main(repo: Path, name: str, rel: str, content: str) -> str:
    git(repo, "checkout", "-q", "-b", name, "main")
    write(repo, rel, content)
    return commit(repo, name)


def _access_repo(tmp_path: Path, filler: int = 0) -> Path:
    repo = tmp_path / "access"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "access.py", _two_functions(filler=filler))
    commit(repo, "base")
    return repo


def test_t_b_11_same_edit_at_a_second_location_is_a_different_binding(tmp_path):
    from scripts.framework.human_authorization import Comment, decide, render_form

    repo = _access_repo(tmp_path)
    head_a = _branch_from_main(repo, "a", "access.py", _two_functions("True", "False"))
    head_b = _branch_from_main(repo, "b", "access.py", _two_functions("False", "True"))
    bind_a = compute_binding(repo, "main", head_a)
    bind_b = compute_binding(repo, "main", head_b)
    assert bind_a.binding != bind_b.binding
    assert bind_a.diff_files == bind_b.diff_files == ("access.py",)
    body = render_form(5, bind_a.binding, ("C7",), bind_a.diff_files)
    comment = Comment(
        1, "u", "scottthurlow", "User", "2026-10-20T10:00:00Z", "2026-10-20T10:00:00Z", body, 1
    )
    bots = frozenset({"hos-worker-hos[bot]"})
    ok = decide(
        [comment],
        frozenset({"scottthurlow"}),
        bots,
        5,
        bind_a.binding,
        ("C7",),
        bind_a.diff_files,
        deletions=(),
    )
    replay = decide(
        [comment],
        frozenset({"scottthurlow"}),
        bots,
        5,
        bind_b.binding,
        ("C7",),
        bind_b.diff_files,
        deletions=(),
    )
    assert ok.authorized
    assert not replay.authorized
    assert [r.reason for r in replay.refusals] == ["stale"]


_SH_BLOCK = "\n".join(
    ['if [ -n "$X" ]; then', "  echo one", "  echo two", "  echo three", "  allowed=ALLOWED"]
    + ["  echo four", "  echo five", "  echo six", "fi", ""]
)


def _gate_sh(first: str, second: str) -> str:
    # Both blocks sit under a column-0 line, so -W starts both hunks at the same kind of line.
    return (
        "start\n"
        + _SH_BLOCK.replace("ALLOWED", first)
        + "start\n"
        + _SH_BLOCK.replace("ALLOWED", second)
    )


def test_t_b_12_function_context_alone_would_collide_but_the_ladder_does_not(tmp_path):
    repo = init(tmp_path)
    write(repo, "gate.sh", _gate_sh("0", "0"))
    commit(repo, "gate")
    head_a = _branch_from_main(repo, "a", "gate.sh", _gate_sh("1", "0"))
    head_b = _branch_from_main(repo, "b", "gate.sh", _gate_sh("0", "1"))

    def raw_function_context_id(head: str) -> str:
        argv = ha._diff_argv(compute_binding(repo, "main", head).merge_base, head, 3)
        argv.insert(argv.index("-O/dev/null"), "--function-context")
        out = ha._run_git(repo, ["patch-id", "--verbatim"], stdin=ha._run_git(repo, argv))
        return out.split()[0].decode()

    assert raw_function_context_id(head_a) == raw_function_context_id(head_b)
    assert (
        compute_binding(repo, "main", head_a).binding
        != compute_binding(repo, "main", head_b).binding
    )


def test_t_b_13_unique_preimages_keep_the_plain_unified_3_patch_id(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    b = compute_binding(repo, "main", head)
    patch = ha._run_git(repo, ha._diff_argv(b.merge_base, head, 3))
    want = ha._run_git(repo, ["patch-id", "--verbatim"], stdin=patch).split()[0].decode()
    assert b.binding == "patch:" + want
    assert ha.CONTEXT_LADDER == (3, 10, 30, 100, 2147483647)


def test_t_b_14_escalated_binding_and_merges_from_main(tmp_path):
    repo = _access_repo(tmp_path, filler=40)
    head = _branch_from_main(repo, "step", "access.py", _two_functions("True", "False", filler=40))
    before = compute_binding(repo, "main", head)

    def merge_main_edit(edit) -> str:
        git(repo, "checkout", "-q", "main")
        text = (repo / "access.py").read_text()
        write(repo, "access.py", edit(text))
        commit(repo, "main edit")
        git(repo, "checkout", "-q", "step")
        git(repo, "merge", "-q", "--no-edit", "main")
        return git(repo, "rev-parse", "HEAD")

    far = merge_main_edit(lambda t: t.replace("# filler 39", "# filler 39 edited"))
    assert compute_binding(repo, "main", far).binding == before.binding  # (i) far edit: ESC-3 holds
    near = merge_main_edit(lambda t: t.replace("    return allowed", "    return bool(allowed)", 1))
    assert (
        compute_binding(repo, "main", near).binding != before.binding
    )  # (ii) edit inside the wider window


def test_t_b_15_ladder_exhaustion_reaches_whole_file_context(tmp_path):
    repo = tmp_path / "flat"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    base = ["same"] * 300
    write(repo, "flat.txt", "\n".join(base) + "\n")
    commit(repo, "base")

    def flipped(n: int) -> str:
        lines = list(base)
        lines[n - 1] = "flipped"
        return "\n".join(lines) + "\n"

    head_a = _branch_from_main(repo, "a", "flat.txt", flipped(120))
    head_b = _branch_from_main(repo, "b", "flat.txt", flipped(180))
    a1, a2 = compute_binding(repo, "main", head_a), compute_binding(repo, "main", head_a)
    b1 = compute_binding(repo, "main", head_b)
    assert a1.binding == a2.binding
    assert a1.binding != b1.binding


def _edge_repo(
    tmp_path: Path, name: str, base_files: dict, step_files: dict, delete=()
) -> tuple[Path, str]:
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    write(repo, "keep.txt", "keep\n")
    for rel, content in base_files.items():
        write(repo, rel, content)
    commit(repo, "base")
    git(repo, "checkout", "-q", "-b", "step")
    for rel, content in step_files.items():
        write(repo, rel, content)
    for rel in delete:
        (repo / rel).unlink()
    return repo, commit(repo, "step")


@pytest.mark.parametrize(
    "base,step,delete",
    [
        ({}, {"new.txt": "n1\nn2\n"}, ()),
        ({"old.txt": "o1\no2\n"}, {}, ("old.txt",)),
        ({"empty.txt": ""}, {"empty.txt": "now has content\n"}, ()),
        ({"noeol.txt": "a\nb\nc"}, {"noeol.txt": "a\nb\nchanged"}, ()),
        ({"blob.bin": b"\x00\x01\x02" * 20}, {"blob.bin": b"\x00\x09\x08" * 20}, ()),
    ],
    ids=["new-file", "deleted-file", "empty-old-blob", "no-trailing-newline", "binary"],
)
def test_t_b_16_edge_shapes_compute(tmp_path, base, step, delete):
    repo, head = _edge_repo(tmp_path, "edge", base, step, delete)
    assert ha.BINDING_RE.fullmatch(compute_binding(repo, "main", head).binding)


def test_t_b_16_pure_addition_with_a_repeated_context_escalates(tmp_path, monkeypatch):
    block = ["p1", "p2", "p3", "p4", "p5", "p6"]
    base = "\n".join(block + ["sep-one"] + block + ["sep-two"]) + "\n"
    step = (
        "\n".join(block[:3] + ["inserted"] + block[3:] + ["sep-one"] + block + ["sep-two"]) + "\n"
    )
    repo, head = _edge_repo(tmp_path, "pure", {"rep.txt": base}, {"rep.txt": step})
    seen: list[list[str]] = []
    real = ha._run_git

    def spy(root, args, **kw):
        seen.append(list(args))
        return real(root, args, **kw)

    monkeypatch.setattr(ha, "_run_git", spy)
    compute_binding(repo, "main", head)
    diffs = [a for a in seen if a[0] == "diff" and "--binary" in a]
    assert "--unified=3" in diffs[0]
    assert any("--unified=10" in a for a in diffs)


def test_t_b_16_gitlink_sections_are_skipped():
    sha = "a" * 40
    patch = (
        f"diff --git a/sub b/sub\nindex {sha}..{'b' * 40} 160000\n--- a/sub\n+++ b/sub\n"
        f"@@ -1 +1 @@\n-Subproject commit {sha}\n+Subproject commit {'b' * 40}\n"
    ).encode()
    assert ha._hunks_anchored(".", patch) is True


_SYN_HEAD = "diff --git a/f b/f\nindex {old}..{new} 100644\n--- a/f\n+++ b/f\n"


def test_t_b_17_parser_fails_closed(monkeypatch):
    monkeypatch.setattr(ha, "_run_git", lambda root, args, **kw: b"something else entirely\n")
    old, new = "a" * 40, "b" * 40
    head = _SYN_HEAD.format(old=old, new=new)
    absent = (head + "@@ -1,2 +1,2 @@\n context\n-gone\n+new\n").encode()
    truncated = (head + "@@ -1,3 +1,3 @@\n only-one-line\n").encode()
    bad_index = (_SYN_HEAD.format(old="xyz", new=new) + "@@ -1 +1 @@\n-gone\n+new\n").encode()
    for patch in (absent, truncated, bad_index):
        with pytest.raises(VerifierError) as e:
            ha._hunks_anchored(".", patch)
        assert e.value.code == "git-failure"


def test_hunk_with_garbage_body_line_fails_closed():
    head = _SYN_HEAD.format(old="a" * 40, new="b" * 40)
    with pytest.raises(VerifierError) as e:
        ha._hunks_anchored(".", (head + "@@ -1 +1 @@\n?weird\n").encode())
    assert e.value.code == "git-failure"


# ---------------------------------------------------------------------------
# S1b (#2151, TD-2101 §10.4.6): wall-time budget, hoisted blob cache, size cap
# ---------------------------------------------------------------------------


def _fake_clock(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(ha.time, "monotonic", lambda: clock[0])
    return clock


def test_t_b_18_budget_is_checked_before_each_git_call(tmp_path, monkeypatch):
    repo = init(tmp_path)
    head = step_branch(repo)
    clock = _fake_clock(monkeypatch)
    real = ha._run_git
    calls: list[list[str]] = []

    def slow(root, args, **kw):
        calls.append(list(args))
        out = real(root, args, **kw)
        clock[0] += ha.BINDING_BUDGET_SECONDS / 2 + 1
        return out

    monkeypatch.setattr(ha, "_run_git", slow)
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", head)
    assert e.value.code == "budget-exhausted"
    assert len(calls) == 2


def test_t_b_19_deadline_is_per_call_not_set_at_import(tmp_path, monkeypatch):
    repo = init(tmp_path)
    head = step_branch(repo)
    clock = _fake_clock(monkeypatch)
    clock[0] = 10 * ha.BINDING_BUDGET_SECONDS
    first = compute_binding(repo, "main", head)
    second = compute_binding(repo, "main", head)
    assert first == second


def test_t_b_20_each_old_blob_is_read_once_across_rungs(tmp_path, monkeypatch):
    repo = _access_repo(tmp_path)
    head = _branch_from_main(repo, "a", "access.py", _two_functions("True", "False"))
    seen: list[list[str]] = []
    real = ha._run_git

    def spy(root, args, **kw):
        seen.append(list(args))
        return real(root, args, **kw)

    monkeypatch.setattr(ha, "_run_git", spy)
    compute_binding(repo, "main", head)
    diffs = [a for a in seen if a[0] == "diff" and "--binary" in a]
    assert len(diffs) >= 2
    blob_reads = [tuple(a) for a in seen if a[:2] == ["cat-file", "blob"]]
    assert blob_reads and len(blob_reads) == len(set(blob_reads))


def test_t_b_21_every_git_call_is_budgeted_static():
    src = Path(ha.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)

    def calls_run_git(node: ast.AST) -> list[ast.Call]:
        return [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_run_git"
        ]

    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    allowed = calls_run_git(funcs["_git_budgeted"])
    assert len(allowed) == 1
    assert len(calls_run_git(tree)) == len(allowed)

    body = funcs["compute_binding"].body
    first = (
        body[1]
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        else body[0]
    )
    assert isinstance(first, ast.Assign) and first.targets[0].id == "deadline"
    assert "monotonic" in ast.dump(first.value)

    for stmt in tree.body:
        if isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            assert "monotonic" not in ast.dump(stmt)


def test_t_b_22_size_cap_on_patch_and_cumulative_blobs(tmp_path, monkeypatch):
    # (i) every rung's patch is capped
    repo = init(tmp_path)
    head = step_branch(repo)
    monkeypatch.setattr(ha, "BINDING_BYTES_MAX", 64)
    with pytest.raises(VerifierError) as e:
        compute_binding(repo, "main", head)
    assert e.value.code == "patch-too-large"
    monkeypatch.undo()

    # (ii) rung 3 passes the cap, rung 10 does not
    repo2 = _access_repo(tmp_path)
    head2 = _branch_from_main(repo2, "a", "access.py", _two_functions("True", "False"))
    mb = compute_binding(repo2, "main", head2).merge_base
    rung3 = ha._run_git(repo2, ha._diff_argv(mb, head2, 3))
    monkeypatch.setattr(ha, "BINDING_BYTES_MAX", len(rung3) + 1)
    seen: list[list[str]] = []
    real = ha._run_git

    def spy(root, args, **kw):
        seen.append(list(args))
        return real(root, args, **kw)

    monkeypatch.setattr(ha, "_run_git", spy)
    with pytest.raises(VerifierError) as e:
        compute_binding(repo2, "main", head2)
    assert e.value.code == "patch-too-large"
    assert any("--unified=10" in a for a in seen if a[0] == "diff")
    monkeypatch.undo()

    # (iii) cumulative old-blob bytes
    patch = (
        _SYN_HEAD.format(old="a" * 40, new="b" * 40) + "@@ -1,2 +1,2 @@\n context\n-gone\n+new\n"
    ).encode()
    blob = b"context\ngone\n" + b"p" * (len(patch) + 50 - len(b"context\ngone\n"))

    def fake(root, args, **kw):
        return patch if args[0] == "diff" else blob

    monkeypatch.setattr(ha, "_run_git", fake)
    monkeypatch.setattr(ha, "BINDING_BYTES_MAX", len(patch) + 1)
    with pytest.raises(VerifierError) as e:
        ha._anchored_patch(".", "a" * 40, "b" * 40, deadline=math.inf)
    assert e.value.code == "patch-too-large"
    assert e.value.detail == "old blobs exceed size cap"


def test_t_b_23_default_cap_does_not_move_the_common_case(tmp_path):
    repo = init(tmp_path)
    head = step_branch(repo)
    b = compute_binding(repo, "main", head)
    patch = ha._run_git(repo, ha._diff_argv(b.merge_base, head, 3))
    want = ha._run_git(repo, ["patch-id", "--verbatim"], stdin=patch).split()[0].decode()
    assert b.binding == "patch:" + want


def test_t_b_24_git_call_timeout_is_capped_by_remaining_budget(monkeypatch):
    clock = _fake_clock(monkeypatch)
    seen: list[float] = []
    monkeypatch.setattr(ha, "_run_git", lambda root, args, **kw: seen.append(kw["timeout"]) or b"")
    now = clock[0]
    ha._git_budgeted("r", ["status"], now + 10)
    ha._git_budgeted("r", ["status"], now + 10_000)
    ha._git_budgeted("r", ["status"], now)
    assert seen == [10, ha.GIT_TIMEOUT_SECONDS, 0]
    with pytest.raises(VerifierError) as e:
        ha._git_budgeted("r", ["status"], now - 1)
    assert e.value.code == "budget-exhausted"


def test_t_b_24b_run_git_passes_timeout_to_subprocess(monkeypatch):
    seen: list[float] = []

    def fake_run(argv, **kw):
        seen.append(kw["timeout"])
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(ha.subprocess, "run", fake_run)
    ha._run_git("r", ["status"], timeout=3)
    ha._run_git("r", ["status"])
    assert seen == [3, ha.GIT_TIMEOUT_SECONDS]
