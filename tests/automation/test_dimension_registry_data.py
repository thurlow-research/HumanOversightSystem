"""
Tests for the REAL dimension-registry data shipped by W5b
(ADR-1643 TD Amendment D, TD-D39): contract/dimensions/{core,project}.yaml,
the project.yaml.template example, the eight prompt files, and the django and
astro pack files.

Unlike test_dimension_registry.py (tmp-tree-only, W5a), these tests deliberately
read the real tree. Nothing here shells out to run_post_change_sweep.sh (W5c
rewrites it).

Covers T5.28 (characterization, TD-D40), T5.49, T5.50, T5.51, T5.52, T5.53, and
T5.63 (the CORE `tools:` allowlist, Amendment E).

T5.28 — the old output is a FROZEN TABLE captured once from the pre-W5c script:
    bash scripts/framework/run_post_change_sweep.sh <the 42 corpus paths>
at commit 7330962bb, parsing the "Domain routing:" block. After W5c the table is
history, which is what a characterization test is. The only expected
narrowings versus the old script are:
    X1  framework-validator leaves the consumer registry (still compared here
        through HOS's PROJECT layer).
    X2  the discretionary "privacy-reviewer (check if PII-relevant)" line.
    X3  TD-D13's exclusion of Tracks 3-5 (unit-test, ux-designer -> ui-reviewer,
        pm-agent); the DOMAIN_AGENTS empty sets for tests/design-pack/spec.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
from pathlib import Path

import pytest
import yaml

from scripts.automation.lib import dimension_registry as dr

REPO_ROOT = Path(__file__).resolve().parents[2]
DIM = REPO_ROOT / "contract" / "dimensions"
PROMPTS = DIM / "prompts"
PACK_FILES = {n: REPO_ROOT / "packs" / n / "dimensions.yaml" for n in ("django", "astro")}
TEMPLATE = DIM / "project.yaml.template"
JUDGMENT_IDS = (
    "code-review",
    "security",
    "privacy",
    "reliability",
    "ops",
    "ui",
    "a11y",
    "infra",
)

EXPECTED_ENTRIES = {
    "code-review",
    "security",
    "privacy",
    "reliability",
    "ops",
    "ui",
    "a11y",
    "infra",
    "lint",
    "type-check",
    "secret-scan",
    "security-scan",
    "bash-check",
    "portability",
    "template-refs",
    "collection-integrity",
    "cross-vendor-review",
}
CORE_BINDING_IDS = {
    "core:code-review/code",
    "core:security/code",
    "core:reliability/code",
    "core:ops/code",
    "core:privacy/governance",
    "core:infra/deploy",
    "core:ui/markup",
    "core:a11y/markup",
    "core:lint/all",
    "core:type-check/all",
    "core:secret-scan/all",
    "core:security-scan/all",
    "core:bash-check/all",
    "core:portability/all",
    "core:template-refs/all",
    "core:collection-integrity/all",
    "core:cross-vendor-review/all",
}
DJANGO_IDS = {
    "pack-django:code-review/app",
    "pack-django:code-review/migrations",
    "pack-django:ui/templates",
    "pack-django:a11y/templates",
    "pack-django:privacy/pii-words",
    "pack-django:deterministic/django-check",
}
ASTRO_IDS = {
    "pack-astro:code-review/astro",
    "pack-astro:security/astro",
    "pack-astro:ui/astro",
    "pack-astro:a11y/astro",
    "pack-astro:deterministic/astro-check",
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def stage(tmp: Path, packs: list[str], project_text: str | None) -> Path:
    """Consumer-shaped tree from the real data. Byte/mode-preserving copies, no symlinks."""
    (tmp / "contract" / "dimensions").mkdir(parents=True)
    shutil.copy2(DIM / "core.yaml", tmp / "contract" / "dimensions" / "core.yaml")
    shutil.copytree(PROMPTS, tmp / "contract" / "dimensions" / "prompts")
    shutil.copytree(DIM / "postures", tmp / "contract" / "dimensions" / "postures")
    shutil.copytree(REPO_ROOT / ".claude" / "agents", tmp / ".claude" / "agents")
    shutil.copytree(
        REPO_ROOT / "scripts" / "oversight" / "gates",
        tmp / "scripts" / "oversight" / "gates",
        copy_function=shutil.copy2,
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(
        REPO_ROOT / "scripts" / "run_second_review.sh", tmp / "scripts" / "run_second_review.sh"
    )
    for n in packs:
        src = PACK_FILES.get(n)
        if src is not None:
            (tmp / "contract" / "dimensions" / f"pack-{n}.yaml").write_bytes(src.read_bytes())
    (tmp / "contract" / "resolved-packs.txt").write_text("".join(f"{n}\n" for n in packs))
    if project_text is not None:
        (tmp / "contract" / "dimensions" / "project.yaml").write_text(project_text)
    return tmp


class _DupKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _DupKeyLoader, node: yaml.MappingNode, deep: bool = False):
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"duplicate key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return yaml.SafeLoader.construct_mapping(loader, node, deep)


_DupKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def strict_load(text: str):
    return yaml.load(text, Loader=_DupKeyLoader)  # noqa: S506 - SafeLoader subclass


def template_parts() -> tuple[str, str]:
    """(live header, extracted example YAML) from project.yaml.template."""
    lines = TEMPLATE.read_text(encoding="utf-8").split("\n")
    begin = lines.index("# --- example: begin ---")
    end = lines.index("# --- example: end ---")
    header = "\n".join(lines[:begin]) + "\n"
    live = "\n".join(ln for ln in header.split("\n") if not ln.startswith("#")) + "\n"
    body = []
    for ln in lines[begin + 1 : end]:
        assert ln == "#" or ln.startswith("# "), f"example line not '#'-prefixed: {ln!r}"
        body.append(re.sub(r"^# ?", "", ln))
    return live, "\n".join(body) + "\n"


def core_titles() -> dict[str, str]:
    doc = yaml.safe_load((DIM / "core.yaml").read_text(encoding="utf-8"))
    return {e["id"]: e["title"] for e in doc["entries"] if e["kind"] == "judgment"}


# ---------------------------------------------------------------------------
# T5.49 — HOS's own committed registry
# ---------------------------------------------------------------------------


def test_t5_49_hos_registry_loads_green():
    assert dr.read_resolved_packs(REPO_ROOT) == ()
    reg = dr.load(REPO_ROOT)
    assert set(reg.entries) == EXPECTED_ENTRIES
    assert set(reg.bindings) == CORE_BINDING_IDS | {"project:code-review/framework-validator"}
    assert reg.source_files == (
        "contract/dimensions/core.yaml",
        "contract/dimensions/project.yaml",
    )


# ---------------------------------------------------------------------------
# T5.50 — real pack files, staged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "packs,extra",
    [
        (["django"], DJANGO_IDS),
        (["node", "astro"], ASTRO_IDS),
        (["django", "node", "astro"], DJANGO_IDS | ASTRO_IDS),
    ],
)
def test_t5_50_real_packs_load(tmp_path, packs, extra):
    root = stage(tmp_path, packs, None)
    reg = dr.load(root, packs=packs)
    assert set(reg.bindings) == CORE_BINDING_IDS | extra


def test_t5_50_three_pack_lint_resolves_all_three(tmp_path):
    packs = ["django", "node", "astro"]
    reg = dr.load(stage(tmp_path, packs, None), packs=packs)
    ids = {b.id for b in reg.bindings.values() if b.entry == "lint"}
    assert ids == {
        "core:lint/all",
        "pack-django:deterministic/django-check",
        "pack-astro:deterministic/astro-check",
    }


# ---------------------------------------------------------------------------
# T5.51 — the prompt-file contract (TD-D33)
# ---------------------------------------------------------------------------

CANONICAL = (
    "# Review dimension: {eid}\n"
    "\n"
    "## Scope\n"
    "\n"
    "Dimension title: {title}\n"
    "\n"
    "Review only the changed files that this dimension selected.\n"
    "You may read other repository files only to understand the selected files.\n"
    "\n"
    "## Boundaries\n"
    "\n"
    "This prompt does not add to, remove from, or override your agent definition.\n"
    "Other review dimensions run separately. Do not report their findings here.\n"
)
BOUNDARY_SENTENCE = "This prompt does not add to, remove from, or override your agent definition."


def _agent_names() -> list[str]:
    lines = (REPO_ROOT / "scripts" / "framework" / "consumer_agents.txt").read_text().splitlines()
    names = [ln.strip() for ln in lines if ln.strip() and not ln.lstrip().startswith("#")]
    return names + ["framework-validator"]


def test_t5_51_prompt_files_exactly_the_eight():
    assert sorted(p.stem for p in PROMPTS.glob("*")) == sorted(JUDGMENT_IDS)
    assert all(p.suffix == ".md" for p in PROMPTS.glob("*"))


def _prompt(eid: str) -> tuple[bytes, str]:
    raw = (PROMPTS / f"{eid}.md").read_bytes()
    return raw, raw.decode("utf-8")


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule1_encoding_and_length(eid):
    raw, text = _prompt(eid)
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert len(text.split("\n")) - 1 <= 20


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule2_title_line(eid):
    _, text = _prompt(eid)
    assert eid in core_titles()
    assert text.split("\n")[0] == f"# Review dimension: {eid}"


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule3_sections(eid):
    _, text = _prompt(eid)
    headings = [ln for ln in text.split("\n") if ln.startswith("#") and not ln.startswith("# ")]
    assert headings == ["## Scope", "## Boundaries"]


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule4_scope_has_title(eid):
    _, text = _prompt(eid)
    scope = text.split("## Boundaries")[0]
    assert core_titles()[eid] in scope


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule5_boundaries(eid):
    _, text = _prompt(eid)
    boundaries = text.split("## Boundaries")[1]
    assert BOUNDARY_SENTENCE in boundaries
    assert "run separately" in boundaries


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule6_agent_names_banned(eid):
    _, text = _prompt(eid)
    for name in _agent_names():
        assert not re.search(rf"(?i)(?<![a-z0-9-]){re.escape(name)}(?![a-z0-9-])", text), name


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule6_delimiters_and_words_banned(eid):
    _, text = _prompt(eid)
    for bad in ("{{", "}}", "{%", "${", "```"):
        assert bad not in text
    assert not re.search(r"(?i)\bverdict", text)
    assert not re.search(r"(?i)\bapplicab", text)


@pytest.mark.parametrize("eid", JUDGMENT_IDS)
def test_t5_51_rule7_canonical_bytes(eid):
    raw, _ = _prompt(eid)
    assert raw == CANONICAL.format(eid=eid, title=core_titles()[eid]).encode("utf-8")


def _all_shipped_bindings() -> list[dict]:
    docs = [DIM / "core.yaml", DIM / "project.yaml", *PACK_FILES.values()]
    out: list[dict] = []
    for p in docs:
        out.extend(yaml.safe_load(p.read_text(encoding="utf-8")).get("bindings", []))
    return out


def test_t5_51_binding_rule_prompt_template_is_entry_prompt():
    judgments = [b for b in _all_shipped_bindings() if b["kind"] == "judgment"]
    assert len(judgments) == 8 + 1 + 5 + 4  # core, HOS project, django, astro
    for b in judgments:
        assert b["prompt_template"] == f"contract/dimensions/prompts/{b['entry']}.md", b["id"]


# ---------------------------------------------------------------------------
# T5.52 — no duplicate keys in shipped YAML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [DIM / "core.yaml", DIM / "project.yaml", *PACK_FILES.values()],
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_t5_52_no_duplicate_keys(path):
    assert strict_load(path.read_text(encoding="utf-8")) is not None


def test_t5_52_template_example_no_duplicate_keys():
    live, example = template_parts()
    assert strict_load(live) is not None
    assert set(strict_load(example)) == {"bindings", "suppress"}


def test_t5_52_loader_detects_duplicates():
    with pytest.raises(yaml.YAMLError):
        strict_load("a: 1\na: 2\n")


# ---------------------------------------------------------------------------
# T5.53 — the template example is valid and does what it says
# ---------------------------------------------------------------------------


def test_t5_53_template_example_loads_and_suppresses(tmp_path):
    live, example = template_parts()
    root = stage(tmp_path, ["django"], live + example)
    reg = dr.load(root, packs=["django"])
    assert "pack-django:privacy/pii-words" not in reg.bindings
    reason = reg.suppressions["pack-django:privacy/pii-words"]
    expected = strict_load(example)["suppress"][0]["reason"]
    assert " ".join(reason.split()) == " ".join(expected.split())
    privacy = {b.id for b in reg.bindings.values() if b.entry == "privacy"}
    assert privacy == {"core:privacy/governance", "project:privacy/app-modules"}


# ---------------------------------------------------------------------------
# T5.28 — characterization against the frozen pre-W5c routing table
# ---------------------------------------------------------------------------

ABBREV = {
    "cr": "code-reviewer",
    "sec": "security-reviewer",
    "priv": "privacy-reviewer",
    "rel": "reliability-reviewer",
    "ops": "ops-reviewer",
    "fv": "framework-validator",
    "a11y": "a11y-reviewer",
    "ui": "ui-reviewer",
    "infra": "infra-reviewer",
}

DOMAIN_AGENTS = {
    "framework": {"framework-validator"},
    "application-code": {"code-reviewer", "security-reviewer"},
    "migrations": {"code-reviewer", "security-reviewer"},
    "templates": {"ui-reviewer", "a11y-reviewer"},
    "infrastructure": {"infra-reviewer"},
    "tests": set(),
    "design-pack": set(),
    "spec": set(),
}

# (path, OLD_DOMAINS, NEW_EXPECTED) — "" means empty.
T528_TABLE = [
    (".claude/agents/coder.md", "framework", "fv"),
    ("scripts/framework/run_post_change_sweep.sh", "framework", "cr fv ops rel sec"),
    ("docs/AGENTS.md", "framework", "fv"),
    ("docs/OVERSIGHT-RUNBOOK.md", "framework", "fv"),
    ("AGENTS.md", "", "fv"),
    ("CLAUDE.md", "", "fv"),
    ("bin/hos-cron", "", "fv infra"),
    ("bootstrap/hos_install.sh", "", "cr fv ops rel sec"),
    ("contract/OVERSIGHT-CONTRACT.md", "", "fv"),
    ("myapp/views.py", "application-code", "cr ops rel sec"),
    ("accounts/models.py", "application-code", "cr ops priv rel sec"),
    ("booking/services.py", "application-code", "cr ops priv rel sec"),
    ("manage.py", "application-code", "cr ops rel sec"),
    ("myapp/pii_export.py", "application-code", "cr ops priv rel sec"),
    ("myapp/PII_Export.py", "application-code", "cr ops priv rel sec"),
    ("myapp/erasure.py", "application-code", "cr ops priv rel sec"),
    ("scripts/oversight/validators/schema.py", "", "cr ops rel sec"),
    ("scripts/automation/lib/github.py", "", "cr ops priv rel sec"),
    ("myapp/migrations/0001_initial.py", "migrations", "cr ops rel sec"),
    ("accounts/migrations/0002_erasure.py", "migrations", "cr ops priv rel sec"),
    ("myapp/templates/myapp/index.html", "templates", "a11y ui"),
    ("templates/base.html", "", "a11y ui"),
    ("static/site.css", "", "ui"),
    ("tests/test_views.py", "tests", "sec"),
    ("myapp/tests/test_models.py", "tests", "ops rel sec"),
    ("conftest.py", "tests", "ops rel sec"),
    ("myapp/test_utils.py", "tests", "ops rel sec"),
    ("docker-compose.yml", "infrastructure", "infra"),
    ("Caddyfile", "infrastructure", "infra"),
    (".env.example", "infrastructure", "infra"),
    ("deploy/.env.example", "infrastructure", "infra"),
    ("scripts/backup.sh", "infrastructure", "cr infra ops rel sec"),
    (".github/workflows/ci.yml", "", "infra sec"),
    ("Specs/v1/design.pack/tokens.json", "design-pack", ""),
    ("Specs/v1/design-pack/notes.md", "design-pack", ""),
    ("Specs/v1/requirements.md", "spec", ""),
    ("README.md", "", ""),
    ("docs/v0.7.0/ADR-1643-deterministic-agent-invocation.md", "", ""),
    ("audit/oversight-log.jsonl", "", "priv"),
    ("frontend/src/app.ts", "", "cr ops rel sec"),
    ("src/pages/index.astro", "", ""),
    ("astro.config.mjs", "", ""),
]


def _agents(spec: str) -> set[str]:
    return {ABBREV[t] for t in spec.split()}


@pytest.fixture(scope="module")
def t528_registry(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("t528")
    hos_project = yaml.safe_load((DIM / "project.yaml").read_text(encoding="utf-8"))
    _, example = template_parts()
    example_bindings = strict_load(example)["bindings"]  # suppress: dropped
    project = {
        "schema": hos_project["schema"],
        "schema_version": hos_project["schema_version"],
        "owner": "project",
        "bindings": hos_project["bindings"] + example_bindings,
    }
    root = stage(tmp, ["django"], yaml.safe_dump(project, sort_keys=False))
    return dr.load(root, packs=["django"])


def _new(reg, path: str) -> set[str]:
    return {
        i.binding.agent
        for i in dr.resolve_for_diff(reg, [path])
        if i.applicable and i.binding.kind == "judgment" and i.binding.agent is not None
    }


def test_t5_28_table_is_the_42_corpus_paths():
    assert len(T528_TABLE) == 42
    assert len({p for p, _, _ in T528_TABLE}) == 42


@pytest.mark.parametrize("path,old,expected", T528_TABLE, ids=[r[0] for r in T528_TABLE])
def test_t5_28_no_unlisted_narrowing_and_exact_pin(t528_registry, path, old, expected):
    new = _new(t528_registry, path)
    old_required = set().union(*(DOMAIN_AGENTS[d] for d in old.split()), set())
    assert old_required <= new, f"{path}: narrowed by {old_required - new}"  # (a)
    assert new == _agents(expected), f"{path}: {sorted(new)}"  # (b)


def test_t5_28_coverage(t528_registry):
    seen_domains = {d for _, old, _ in T528_TABLE for d in old.split()}
    assert seen_domains == set(DOMAIN_AGENTS)  # (c) all 8 domains
    paths = [p for p, _, _ in T528_TABLE]
    plan = {i.binding.id: i for i in dr.resolve_for_diff(t528_registry, paths)}
    for b in t528_registry.bindings.values():
        if b.kind != "judgment":
            continue
        assert plan[b.id].applicable, f"judgment binding {b.id} matches no corpus path"


# ---------------------------------------------------------------------------
# T5.63 — the CORE `tools:` allowlist (TD-D42, #1932)
# ---------------------------------------------------------------------------

_RHA_SPEC = importlib.util.spec_from_file_location(
    "require_human_approval",
    REPO_ROOT / "scripts" / "framework" / "require_human_approval.py",
)
assert _RHA_SPEC is not None and _RHA_SPEC.loader is not None
rha = importlib.util.module_from_spec(_RHA_SPEC)
_RHA_SPEC.loader.exec_module(rha)


def _core_tools() -> list[str]:
    return yaml.safe_load((DIM / "core.yaml").read_text(encoding="utf-8"))["tools"]


def test_t5_63_tools_sorted_and_exactly_the_shipped_deterministic_tools():
    tools = _core_tools()
    assert tools == sorted(tools)
    shipped = {b["tool"] for b in _all_shipped_bindings() if b["kind"] == "deterministic"}
    assert len(shipped) == 11
    assert set(tools) == shipped
    assert len(tools) == len(set(tools))


def test_t5_63_gate_tools_are_protected_and_only_run_second_review_is_not():
    globs = rha.load_globs(REPO_ROOT / "scripts" / "framework" / "protected_surfaces.txt")
    tools = _core_tools()
    protected = {f for f, _ in rha.matched_surfaces(tools, globs)}
    gates = {t for t in tools if t.startswith("scripts/oversight/gates/")}
    assert gates <= protected
    # Ratchet (TD-D42): fails once #1935 protects run_second_review.sh. Then delete
    # the exemption; do not weaken this to a subset check.
    assert set(tools) - protected == {"scripts/run_second_review.sh"}
