"""Tests for skill caching, invalidation, and load-time gating.

Locks in:
- Cache is populated on first discover_skills() call and reused on subsequent calls
- invalidate_skill_cache() clears the cache so the next call re-reads from disk
- Skills with requires_bins pointing to a missing binary are skipped
- Skills with requires_env pointing to a missing env var are skipped
- When all requirements are met, skills are included normally
- When ANY requirement fails, the skill is skipped (AND semantics)
"""

import pytest

import llm.skills as skills_module
from llm.skills import (
    _parse_skill_file,
    discover_skills,
    invalidate_skill_cache,
)


@pytest.fixture(autouse=True)
def _clear_skill_cache():
    """Invalidate the skill cache before and after each test."""
    invalidate_skill_cache()
    yield
    invalidate_skill_cache()


def _make_skill_md(
    directory,
    name,
    description="A test skill",
    tools="read-only",
    *,
    requires_bins="",
    requires_env="",
):
    """Helper: create a minimal SKILL.md inside a named subdirectory."""
    skill_dir = directory / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    metadata_lines = [f"  tools: {tools}"]
    if requires_bins:
        metadata_lines.append(f"  requires_bins: {requires_bins}")
    if requires_env:
        metadata_lines.append(f"  requires_env: {requires_env}")

    metadata_block = "\n".join(metadata_lines)
    (skill_dir / "SKILL.md").write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"metadata:\n"
        f"{metadata_block}\n"
        f"---\n\n"
        f"System prompt for {name}."
    )
    return skill_dir


class TestSkillCache:
    def test_cache_populated_on_first_call(self):
        """After calling discover_skills(), the internal cache is not None."""
        assert skills_module._skill_cache is None
        discover_skills()
        assert skills_module._skill_cache is not None

    def test_second_call_returns_cached(self):
        """Second call returns the exact same dict object (identity, not just equality)."""
        first = discover_skills()
        second = discover_skills()
        assert first is second

    def test_invalidate_clears_cache(self):
        """invalidate_skill_cache() sets the internal cache back to None."""
        discover_skills()
        assert skills_module._skill_cache is not None
        invalidate_skill_cache()
        assert skills_module._skill_cache is None

    def test_discover_after_invalidate_rereads(self, tmp_path):
        """After invalidation, discover_skills() re-reads from disk and picks up changes."""
        _make_skill_md(tmp_path, "dynamic-skill", description="Version 1")
        first = discover_skills([tmp_path])
        assert first["dynamic-skill"].description == "Version 1"

        # Modify the skill file on disk
        invalidate_skill_cache()
        _make_skill_md(tmp_path, "dynamic-skill", description="Version 2")
        second = discover_skills([tmp_path])

        assert second["dynamic-skill"].description == "Version 2"
        assert first is not second


class TestLoadTimeGating:
    def test_skill_skipped_when_binary_missing(self, tmp_path):
        """A skill requiring a non-existent binary is not returned."""
        skill_dir = _make_skill_md(
            tmp_path, "needs-missing-bin", requires_bins="nonexistent_binary_xyz_12345"
        )
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is None

    def test_skill_included_when_binary_present(self, tmp_path):
        """A skill requiring python3 (which exists on any dev machine) is included."""
        skill_dir = _make_skill_md(tmp_path, "needs-python", requires_bins="python3")
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is not None
        assert result.name == "needs-python"

    def test_skill_skipped_when_env_var_missing(self, tmp_path, monkeypatch):
        """A skill requiring a non-existent env var is skipped."""
        monkeypatch.delenv("NONEXISTENT_VAR_XYZ_98765", raising=False)
        skill_dir = _make_skill_md(tmp_path, "needs-env", requires_env="NONEXISTENT_VAR_XYZ_98765")
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is None

    def test_skill_included_when_env_var_set(self, tmp_path, monkeypatch):
        """When the required env var is set, the skill is included."""
        monkeypatch.setenv("ASTRYN_TEST_GATING_VAR", "1")
        skill_dir = _make_skill_md(tmp_path, "has-env", requires_env="ASTRYN_TEST_GATING_VAR")
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is not None
        assert result.name == "has-env"

    def test_multiple_requirements_all_must_pass(self, tmp_path, monkeypatch):
        """If a skill has both requires_bins and requires_env, ALL must pass."""
        # Binary exists (python3) but env var does not -- skill should be skipped
        monkeypatch.delenv("NONEXISTENT_MULTI_VAR_XYZ", raising=False)
        skill_dir = _make_skill_md(
            tmp_path,
            "needs-both",
            requires_bins="python3",
            requires_env="NONEXISTENT_MULTI_VAR_XYZ",
        )
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is None

    def test_multiple_requirements_all_pass(self, tmp_path, monkeypatch):
        """When both requires_bins and requires_env are satisfied, skill is included."""
        monkeypatch.setenv("ASTRYN_TEST_MULTI_VAR", "yes")
        skill_dir = _make_skill_md(
            tmp_path,
            "has-both",
            requires_bins="python3",
            requires_env="ASTRYN_TEST_MULTI_VAR",
        )
        result = _parse_skill_file(skill_dir / "SKILL.md")
        assert result is not None
        assert result.name == "has-both"

    def test_gated_skill_excluded_from_discover(self, tmp_path, monkeypatch):
        """discover_skills() omits skills that fail load-time gating."""
        monkeypatch.delenv("NONEXISTENT_DISCOVER_VAR", raising=False)
        _make_skill_md(tmp_path, "gated-out", requires_env="NONEXISTENT_DISCOVER_VAR")
        skills = discover_skills([tmp_path])
        assert "gated-out" not in skills

    def test_gated_skill_included_in_discover_when_met(self, tmp_path, monkeypatch):
        """discover_skills() includes skills whose requirements are met."""
        monkeypatch.setenv("ASTRYN_DISCOVER_VAR", "ok")
        _make_skill_md(tmp_path, "gated-in", requires_env="ASTRYN_DISCOVER_VAR")
        skills = discover_skills([tmp_path])
        assert "gated-in" in skills
