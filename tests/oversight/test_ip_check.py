"""
Tests for ip_check.py — IP/provenance validator.

classify_license() is a pure-logic function with well-defined behavior
and clear mutation targets (string membership checks, score thresholds).
The requirement-parsing logic is tested with temp files.
"""
import json
import tempfile
import os
import pytest
from io import BytesIO
from unittest.mock import patch, MagicMock

from ip_check import (
    classify_license,
    check_dependency_licenses,
    check_prompt_cleanroom,
    check_regurgitation_stub,
    analyse_files,
    _pypi_license,
    _npm_license,
    _scancode_license,
    COPYLEFT,
    PERMISSIVE,
    UNKNOWN_MARKERS,
    _COPYLEFT_SCORE,
    _PERMISSIVE_SCORE,
    _UNKNOWN_SCORE,
)


# ── classify_license() — primary mutation target ──────────────────────────────

class TestClassifyLicense:
    # None / unknown markers
    def test_none_is_unknown(self):
        category, score = classify_license(None)
        assert category == "unknown"
        assert score == pytest.approx(_UNKNOWN_SCORE)

    def test_empty_string_is_unknown(self):
        category, _ = classify_license("")
        assert category == "unknown"

    @pytest.mark.parametrize("marker", list(UNKNOWN_MARKERS)[:5])
    def test_known_unknown_markers(self, marker):
        category, _ = classify_license(marker)
        assert category == "unknown"

    # Copyleft licenses
    def test_gpl2_is_copyleft(self):
        category, score = classify_license("GPL-2.0")
        assert category == "copyleft"
        assert score == pytest.approx(_COPYLEFT_SCORE)

    def test_gpl3_is_copyleft(self):
        category, _ = classify_license("GPL-3.0")
        assert category == "copyleft"

    def test_agpl_is_copyleft(self):
        category, _ = classify_license("AGPL-3.0")
        assert category == "copyleft"

    def test_lgpl_is_copyleft(self):
        category, _ = classify_license("LGPL-2.1")
        assert category == "copyleft"

    def test_copyleft_case_insensitive(self):
        category, _ = classify_license("gpl-2.0")
        assert category == "copyleft"

    # Permissive licenses
    def test_mit_is_permissive(self):
        category, score = classify_license("MIT")
        assert category == "permissive"
        assert score == pytest.approx(_PERMISSIVE_SCORE)

    def test_apache2_is_permissive(self):
        category, _ = classify_license("Apache-2.0")
        assert category == "permissive"

    def test_bsd_is_permissive(self):
        category, _ = classify_license("BSD-3-Clause")
        assert category == "permissive"

    def test_permissive_case_insensitive(self):
        category, _ = classify_license("mit")
        assert category == "permissive"

    # Unknown proprietary
    def test_proprietary_unknown(self):
        category, _ = classify_license("Proprietary Commercial License 2.0")
        assert category == "unknown"

    # Score ordering
    def test_copyleft_score_higher_than_permissive(self):
        _, cop_score = classify_license("GPL-2.0")
        _, per_score = classify_license("MIT")
        assert cop_score > per_score

    def test_unknown_score_between_permissive_and_copyleft(self):
        _, unk = classify_license(None)
        _, per = classify_license("MIT")
        _, cop = classify_license("GPL-2.0")
        assert per <= unk <= cop

    # Mutation-resistant boundary tests
    def test_copyleft_set_is_non_empty(self):
        assert len(COPYLEFT) > 0

    def test_permissive_set_is_non_empty(self):
        assert len(PERMISSIVE) > 0

    def test_copyleft_and_permissive_disjoint(self):
        overlap = set(c.upper() for c in COPYLEFT) & set(p.upper() for p in PERMISSIVE)
        assert overlap == set(), f"overlapping license tags: {overlap}"


# ── check_dependency_licenses() — file parsing ───────────────────────────────

class TestCheckDependencyLicenses:
    def _write(self, name: str, content: str) -> str:
        d = tempfile.mkdtemp()
        path = os.path.join(d, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_requirements_txt_parsed(self):
        path = self._write("requirements.txt", "requests>=2.28\ndjango>=4.0\n")
        try:
            # Mock license lookup to return MIT so we get permissive findings
            with patch("ip_check._pypi_license", return_value="MIT"):
                findings = check_dependency_licenses([path])
            # Should produce permissive findings for both packages
            assert isinstance(findings, list)
        finally:
            os.unlink(path)

    def test_requirements_skips_comments(self):
        path = self._write("requirements.txt", "# this is a comment\nrequests>=2.0\n")
        try:
            with patch("ip_check._pypi_license", return_value="MIT"):
                findings = check_dependency_licenses([path])
            # Only one package (requests), not the comment
            pkg_names = [f["package"] for f in findings]
            assert "this" not in pkg_names
        finally:
            os.unlink(path)

    def test_package_json_parsed(self):
        pkg = json.dumps({
            "name": "myapp",
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
        })
        path = self._write("package.json", pkg)
        try:
            with patch("ip_check._npm_license", return_value="MIT"):
                findings = check_dependency_licenses([path])
            assert isinstance(findings, list)
        finally:
            os.unlink(path)

    def test_nonexistent_file_skipped(self):
        findings = check_dependency_licenses(["/does/not/exist/requirements.txt"])
        assert findings == []

    def test_copyleft_package_produces_high_severity_finding(self):
        path = self._write("requirements.txt", "gpl-package>=1.0\n")
        try:
            with patch("ip_check._pypi_license", return_value="GPL-3.0"):
                findings = check_dependency_licenses([path])
            assert any(f["severity"] == "high" for f in findings)
        finally:
            os.unlink(path)

    def test_unknown_license_produces_medium_finding(self):
        path = self._write("requirements.txt", "mystery-pkg>=1.0\n")
        try:
            with patch("ip_check._pypi_license", return_value=None):
                findings = check_dependency_licenses([path])
            assert any(f["severity"] == "medium" for f in findings)
        finally:
            os.unlink(path)


# ── _pypi_license() and _npm_license() ───────────────────────────────────────

class TestAPILookups:
    def test_pypi_license_parses_response(self):
        payload = json.dumps({"info": {"license": "MIT"}}).encode()
        with patch("ip_check.urllib.request.urlopen",
                   return_value=BytesIO(payload)):
            result = _pypi_license("requests")
        assert result == "MIT"

    def test_pypi_license_network_error_returns_none(self):
        with patch("ip_check.urllib.request.urlopen",
                   side_effect=Exception("network error")):
            result = _pypi_license("requests")
        assert result is None

    def test_npm_license_parses_response(self):
        payload = json.dumps({"license": "Apache-2.0"}).encode()
        with patch("ip_check.urllib.request.urlopen",
                   return_value=BytesIO(payload)):
            result = _npm_license("react")
        assert result == "Apache-2.0"

    def test_npm_license_network_error_returns_none(self):
        with patch("ip_check.urllib.request.urlopen",
                   side_effect=Exception("network error")):
            result = _npm_license("react")
        assert result is None

    def test_scancode_license_not_installed(self):
        with patch("ip_check.subprocess.run", side_effect=FileNotFoundError("scancode not found")):
            result = _scancode_license("test.py")
        assert result is None

    def test_scancode_license_parses_output(self):
        scancode_output = json.dumps({
            "files": [{"licenses": [{"spdx_license_key": "MIT"}]}]
        })
        mock = MagicMock(stdout=scancode_output, returncode=0)
        with patch("ip_check.subprocess.run", return_value=mock):
            result = _scancode_license("test.py")
        assert result == "MIT"


# ── analyse_files() ───────────────────────────────────────────────────────────

# ── check_prompt_cleanroom() ──────────────────────────────────────────────────

class TestPromptCleanroom:
    def test_missing_prompts_dir_returns_empty(self):
        findings = check_prompt_cleanroom("/does/not/exist", ["auth/views.py"])
        assert findings == []

    def test_clean_spec_prompt_not_flagged(self):
        tmpdir = tempfile.mkdtemp()
        # Write a clean spec-based prompt artifact
        prompt_path = os.path.join(tmpdir, "views.md")
        with open(prompt_path, "w") as f:
            f.write("Implement per spec §3. Required fields: email, name.\n")
        try:
            with patch("ip_check.subprocess.run",
                       return_value=MagicMock(stdout="", returncode=0)):
                findings = check_prompt_cleanroom(tmpdir, [
                    os.path.join(tmpdir, "views.py")])
        finally:
            import shutil; shutil.rmtree(tmpdir)
        # Clean prompt may produce info findings (positive signal) but not high
        high_findings = [f for f in findings if f["severity"] == "high"]
        assert len(high_findings) == 0


# ── check_regurgitation_stub() ────────────────────────────────────────────────

class TestRegurgitationStub:
    def test_returns_stub_flag(self):
        result = check_regurgitation_stub(["auth/views.py"])
        assert result["stub"] is True
        assert result["integration_active"] is False

    def test_files_checked_count(self):
        result = check_regurgitation_stub(["a.py", "b.py", "c.py"])
        assert result["files_checked"] == 3


# ── analyse_files() ───────────────────────────────────────────────────────────

class TestIPAnalyseFiles:
    def test_no_files(self):
        result = analyse_files([])
        assert result["score"] == pytest.approx(0.0)

    def test_non_manifest_file_low_score(self):
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False) as f:
            f.write("import os\n")
            path = f.name
        try:
            result = analyse_files([path])
            assert 0.0 <= result["score"] <= 1.0
        finally:
            os.unlink(path)

    def test_result_envelope(self):
        result = analyse_files([])
        for key in ("dimension", "score", "raw_value", "weight", "evidence",
                    "checklist_items", "findings", "error"):
            assert key in result

    def test_copyleft_in_requirements_raises_score(self):
        tmpdir = tempfile.mkdtemp()
        req = os.path.join(tmpdir, "requirements.txt")
        with open(req, "w") as f:
            f.write("gpl-package>=1.0\n")
        try:
            with patch("ip_check._pypi_license", return_value="GPL-3.0"):
                result = analyse_files([req])
            assert result["score"] > 0.0
        finally:
            import shutil; shutil.rmtree(tmpdir)
