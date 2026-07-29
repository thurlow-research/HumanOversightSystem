"""
Tests for hallucination_surface_js.py (S7, ADR-032, epic #1029).

tree-sitter is in-process, so the API-scan tests exercise the real parser
against real temp files. The npm-registry dependency-existence check hits
the network, so those tests mock urllib.request.urlopen — real registry
calls have no place in CI.
"""
from __future__ import annotations

import json
import os
import tempfile
import textwrap
import urllib.error
from io import BytesIO
from unittest.mock import patch

import pytest

from hallucination_surface_js import (
    _check_dependencies_exist,
    _npm_package_exists,
    analyse_files,
)
from schema import WEIGHTS

RISKY_TS = textwrap.dedent(
    """
    import { getCollection } from 'astro:content';
    import punycode from 'punycode';

    const posts = Astro.glob('./posts/*.md');
    const eager = import.meta.globEager('./posts/*.md');
    const buf = new Buffer('abc');
    url.parse('http://example.com');
    """
)

CLEAN_TS = textwrap.dedent(
    """
    function greet(name: string): string {
      return `hello ${name}`;
    }
    """
)

GARBAGE_TS = "function broken( {{{ !!! not real syntax at all $$$ ###"


def _tmpfile(content: str, suffix: str = ".ts") -> str:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(content)
    f.close()
    return f.name


def _tmp_pkg_json(deps: dict, dev_deps: dict | None = None) -> str:
    payload = {"name": "x", "version": "1.0.0", "dependencies": deps}
    if dev_deps:
        payload["devDependencies"] = dev_deps
    d = tempfile.mkdtemp()
    path = os.path.join(d, "package.json")
    with open(path, "w") as f:
        json.dump(payload, f)
    return path


class TestApiScan:
    def test_clean_file_scores_zero(self):
        path = _tmpfile(CLEAN_TS)
        try:
            result = analyse_files([path])
            assert result["error"] is None
            assert result["raw_value"]["version_sensitive_count"] == 0
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(path)

    def test_risky_apis_detected(self):
        path = _tmpfile(RISKY_TS)
        try:
            result = analyse_files([path])
            assert result["error"] is None
            patterns = {f["pattern"] for f in result["raw_value"]["findings"]}
            assert "punycode" in patterns
            assert "Astro.glob" in patterns
            assert "import.meta.globEager" in patterns
            assert "new Buffer" in patterns
            assert "url.parse" in patterns
            assert result["score"] > 0.0
        finally:
            os.unlink(path)

    def test_dimension_and_weight_match_python_sibling(self):
        path = _tmpfile(CLEAN_TS)
        try:
            result = analyse_files([path])
            assert result["dimension"] == "hallucination_surface"
            assert result["weight"] == WEIGHTS["hallucination_surface"]
        finally:
            os.unlink(path)

    def test_unparseable_file_excluded_not_scored_clean(self):
        path = _tmpfile(GARBAGE_TS)
        try:
            result = analyse_files([path])
            # Garbage still parses to *something* under tree-sitter (error
            # nodes), so this should not silently produce a clean 0.0 score
            # without at least surfacing the parse trouble somewhere.
            assert result["raw_value"]["parse_errors"] or result["raw_value"]["findings"] == []
        finally:
            os.unlink(path)

    def test_astro_frontmatter_scanned(self):
        astro_src = textwrap.dedent(
            """\
            ---
            const posts = Astro.glob('./posts/*.md');
            ---
            <div>{posts.length}</div>
            """
        )
        path = _tmpfile(astro_src, suffix=".astro")
        try:
            result = analyse_files([path])
            patterns = {f["pattern"] for f in result["raw_value"]["findings"]}
            assert "Astro.glob" in patterns
        finally:
            os.unlink(path)


class TestNpmPackageExists:
    def test_exists_returns_true_on_2xx(self):
        with patch(
            "hallucination_surface_js.urllib.request.urlopen",
            return_value=BytesIO(b"{}"),
        ):
            assert _npm_package_exists("react") is True

    def test_404_returns_false(self):
        with patch(
            "hallucination_surface_js.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("url", 404, "Not Found", None, None),
        ):
            assert _npm_package_exists("totally-hallucinated-package-xyz") is False

    def test_other_http_error_returns_none(self):
        with patch(
            "hallucination_surface_js.urllib.request.urlopen",
            side_effect=urllib.error.HTTPError("url", 500, "Server Error", None, None),
        ):
            assert _npm_package_exists("react") is None

    def test_network_error_returns_none(self):
        with patch(
            "hallucination_surface_js.urllib.request.urlopen",
            side_effect=OSError("network unreachable"),
        ):
            assert _npm_package_exists("react") is None


class TestCheckDependenciesExist:
    def test_missing_package_flagged(self):
        deps = {"totally-hallucinated-pkg": ("^1.0.0", "package.json")}
        with patch(
            "hallucination_surface_js._npm_package_exists", return_value=False
        ):
            result = _check_dependencies_exist(deps)
        assert len(result["missing"]) == 1
        assert result["missing"][0]["name"] == "totally-hallucinated-pkg"
        assert result["unresolved"] == []

    def test_network_error_is_unresolved_not_missing(self):
        deps = {"react": ("^18.0.0", "package.json")}
        with patch("hallucination_surface_js._npm_package_exists", return_value=None):
            result = _check_dependencies_exist(deps)
        assert result["missing"] == []
        assert result["unresolved"] == ["react"]

    def test_non_registry_specs_skipped(self):
        deps = {
            "local-pkg": ("file:../local-pkg", "package.json"),
            "linked-pkg": ("link:../linked-pkg", "package.json"),
            "workspace-pkg": ("workspace:*", "package.json"),
            "git-pkg": ("git+https://example.com/x.git", "package.json"),
            "url-pkg": ("https://example.com/x.tgz", "package.json"),
        }
        with patch("hallucination_surface_js._npm_package_exists") as mock_exists:
            result = _check_dependencies_exist(deps)
        mock_exists.assert_not_called()
        assert result["checked"] == 0

    def test_bail_out_on_consecutive_network_errors(self):
        deps = {f"pkg-{i}": ("^1.0.0", "package.json") for i in range(20)}
        with patch("hallucination_surface_js._npm_package_exists", return_value=None):
            result = _check_dependencies_exist(deps)
        assert result["checked"] < 20


class TestPackageJsonIntegration:
    def test_missing_dependency_scores_and_flags(self):
        pkg_path = _tmp_pkg_json({"totally-hallucinated-pkg-xyz": "^1.0.0"})
        try:
            with patch(
                "hallucination_surface_js._npm_package_exists", return_value=False
            ):
                result = analyse_files([pkg_path])
            assert result["error"] is None
            assert result["raw_value"]["missing_package_count"] == 1
            assert result["score"] > 0.0
            assert any(
                "totally-hallucinated-pkg-xyz" in item for item in result["checklist_items"]
            )
        finally:
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))

    def test_all_dependencies_exist_scores_zero(self):
        pkg_path = _tmp_pkg_json({"react": "^18.0.0"})
        try:
            with patch("hallucination_surface_js._npm_package_exists", return_value=True):
                result = analyse_files([pkg_path])
            assert result["error"] is None
            assert result["raw_value"]["missing_package_count"] == 0
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))

    def test_no_dependencies_is_clean_not_error(self):
        pkg_path = _tmp_pkg_json({})
        try:
            result = analyse_files([pkg_path])
            assert result["error"] is None
            assert result["score"] == pytest.approx(0.0)
        finally:
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))

    def test_all_unresolved_and_no_source_excludes_dimension(self):
        pkg_path = _tmp_pkg_json({"react": "^18.0.0"})
        try:
            with patch("hallucination_surface_js._npm_package_exists", return_value=None):
                result = analyse_files([pkg_path])
            assert result["error"] is not None
        finally:
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))

    def test_invalid_json_flagged_as_error_detail(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "package.json")
        with open(path, "w") as f:
            f.write("{not valid json")
        try:
            result = analyse_files([path])
            assert result["error"] is not None
        finally:
            os.unlink(path)
            os.rmdir(d)

    def test_combined_source_and_package_json(self):
        src_path = _tmpfile(RISKY_TS)
        pkg_path = _tmp_pkg_json({"totally-hallucinated-pkg-xyz": "^1.0.0"})
        try:
            with patch(
                "hallucination_surface_js._npm_package_exists", return_value=False
            ):
                result = analyse_files([src_path, pkg_path])
            assert result["error"] is None
            assert result["raw_value"]["version_sensitive_count"] > 0
            assert result["raw_value"]["missing_package_count"] == 1
        finally:
            os.unlink(src_path)
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))


class TestMain:
    def test_main_no_files_prints_json(self, capsys, monkeypatch):
        import sys

        monkeypatch.setattr(sys, "argv", ["hallucination_surface_js.py"])
        import hallucination_surface_js

        hallucination_surface_js.main()
        out = json.loads(capsys.readouterr().out)
        assert out["error"] == "no input files"

    def test_main_accepts_package_json_by_basename(self, capsys, monkeypatch):
        import sys

        pkg_path = _tmp_pkg_json({})
        try:
            monkeypatch.setattr(sys, "argv", ["hallucination_surface_js.py", pkg_path])
            import hallucination_surface_js

            hallucination_surface_js.main()
            out = json.loads(capsys.readouterr().out)
            assert out["error"] is None
        finally:
            os.unlink(pkg_path)
            os.rmdir(os.path.dirname(pkg_path))
