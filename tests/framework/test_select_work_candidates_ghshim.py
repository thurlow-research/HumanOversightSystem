"""T-ZC2 of docs/v0.7.0/TECHNICAL-DESIGN-1644-T3.0a-no-idle-selection.md §7.2:
the PATH-level fake `gh` request count for scripts/framework/select_work_candidates.py.

The selector runs in a subprocess against a fake `gh` executable on PATH, so
ANY request path is counted, including one that bypasses `_run_gh` (which the
in-process stub in test_select_work_candidates_native.py cannot see). The fake
serves only the three S2 endpoint families and exits 97 on anything else.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_FAKE_GH = """#!{python}
import json, os, re, sys

args = sys.argv[1:]
with open(os.environ["GH_CALLS_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\\n")

ZERO_DEPS = {{"blocked_by": 0, "blocking": 0, "total_blocked_by": 0, "total_blocking": 0}}
ZERO_SUBS = {{"total": 0, "completed": 0, "percent_completed": 0}}


def issue(number, user="ScottThurlow", user_type="User"):
    return {{
        "number": number,
        "title": "issue %d" % number,
        "labels": [{{"name": "needs-ai"}}],
        "user": {{"login": user, "type": user_type}},
        "pull_request": None,
        "issue_dependencies_summary": ZERO_DEPS,
        "sub_issues_summary": ZERO_SUBS,
    }}


if len(args) != 2 or args[0] != "api":
    sys.exit(97)
endpoint = args[1]
if re.match(r"^repos/owner/repo/issues\\?state=open&milestone=5&", endpoint):
    records = [issue(n) for n in (1, 2, 3)]
    records += [issue(n, "outside-contributor", "User") for n in (4, 5)]
    print(json.dumps(records))
elif re.match(r"^repos/owner/repo/issues/4/events\\?", endpoint):
    print(json.dumps([{{
        "event": "labeled",
        "label": {{"name": "needs-ai"}},
        "actor": {{"login": "ScottThurlow", "type": "User"}},
    }}]))
elif re.match(r"^repos/owner/repo/issues/5/events\\?", endpoint):
    print("[]")
elif re.match(r"^repos/owner/repo/collaborators\\?", endpoint):
    print("[]")
else:
    sys.exit(97)
"""


def test_zc2_path_level_fake_gh_sees_exactly_the_three_s2_requests(tmp_path):
    root = tmp_path / "tree"
    (root / ".github").mkdir(parents=True)
    (root / ".github" / "CODEOWNERS").write_text("* @ScottThurlow\n")
    fw = root / "scripts" / "framework"
    fw.mkdir(parents=True)
    (fw / "machine-accounts.env").write_text(
        'BOT_WORKER_USERNAME="hos-worker-hos[bot]"\n'
        'BOT_OVERSEER_USERNAME="hos-overseer-hos[bot]"\n'
        'BOT_HUMAN_USERNAME="scottthurlow-claude[bot]"\n'
        'COPILOT_BOT_LOGIN="copilot[bot]"\n'
    )

    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(_FAKE_GH.format(python=sys.executable))
    gh.chmod(0o755)
    calls_log = tmp_path / "gh-calls.jsonl"

    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "GH_CALLS_LOG": str(calls_log),
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from pathlib import Path; "
            "import scripts.framework.select_work_candidates as s; "
            "s._REPO_ROOT = Path(sys.argv[1]); sys.exit(s.main(sys.argv[2:]))",
            str(root),
            "--repo",
            "owner/repo",
            "--milestone",
            "5",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    calls = [json.loads(ln) for ln in calls_log.read_text().splitlines()]
    assert len(calls) == 3, calls
    assert f"api_requests={len(calls)}" in result.stderr
    assert all(len(argv) == 2 and argv[0] == "api" for argv in calls), calls
    for _, endpoint in calls:
        assert not re.search(r"/dependencies|/sub_issues|/parent|/timeline", endpoint), endpoint
        assert not re.search(r"issues/\d+$", endpoint), endpoint
    assert [re.sub(r"\?.*", "", ep) for _, ep in calls] == [
        "repos/owner/repo/issues",
        "repos/owner/repo/issues/5/events",
        "repos/owner/repo/issues/4/events",
    ]
