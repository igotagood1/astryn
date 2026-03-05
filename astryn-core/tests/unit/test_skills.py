"""Tests for llm/skills.py — skill discovery, parsing, and formatting."""

from llm.skills import (
    SkillDef,
    _parse_simple_yaml,
    _parse_skill_file,
    discover_skills,
    format_available_skills_block,
    load_skill_metadata,
)
from tools.registry import READ_ONLY_TOOLS, REVIEWER_TOOLS, WRITER_TOOLS


class TestDiscoverSkills:
    def test_discovers_builtin_skills(self):
        skills = discover_skills()
        assert "code-writer" in skills
        assert "code-reviewer" in skills

    def test_exactly_two_builtin_skills(self):
        skills = discover_skills()
        assert len(skills) == 2

    def test_all_are_skill_def(self):
        skills = discover_skills()
        for skill in skills.values():
            assert isinstance(skill, SkillDef)

    def test_writer_has_writer_tools(self):
        skills = discover_skills()
        assert skills["code-writer"].tools is WRITER_TOOLS

    def test_reviewer_has_reviewer_tools(self):
        skills = discover_skills()
        assert skills["code-reviewer"].tools is REVIEWER_TOOLS

    def test_skill_prompts_are_nonempty(self):
        skills = discover_skills()
        for skill in skills.values():
            assert len(skill.system_prompt) > 50

    def test_writer_prompt_content(self):
        skills = discover_skills()
        assert "code-writer" in skills["code-writer"].system_prompt.lower()

    def test_reviewer_prompt_content(self):
        skills = discover_skills()
        assert "code-reviewer" in skills["code-reviewer"].system_prompt.lower()

    def test_writer_cannot_commit(self):
        skills = discover_skills()
        assert "cannot commit" in skills["code-writer"].system_prompt.lower()

    def test_reviewer_cannot_write(self):
        skills = discover_skills()
        assert "cannot write" in skills["code-reviewer"].system_prompt.lower()


class TestUserSkillOverrides:
    def test_user_skill_overrides_builtin(self, tmp_path):
        """User skills with same name override built-in skills."""
        skill_dir = tmp_path / "my-writer"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: code-writer\n"
            "description: Custom writer skill\n"
            "metadata:\n"
            "  tools: read-only\n"
            "---\n\n"
            "Custom writer instructions."
        )

        skills = discover_skills([tmp_path])
        assert skills["code-writer"].description == "Custom writer skill"
        assert skills["code-writer"].tools is READ_ONLY_TOOLS

    def test_user_adds_new_skill(self, tmp_path):
        """User can add entirely new skills."""
        skill_dir = tmp_path / "data-analysis"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: data-analysis\n"
            "description: Analyze data sets\n"
            "metadata:\n"
            "  tools: read-only\n"
            "  model: deepseek-r1:7b\n"
            "---\n\n"
            "You are a data analysis specialist."
        )

        skills = discover_skills([tmp_path])
        assert "data-analysis" in skills
        assert skills["data-analysis"].preferred_model == "deepseek-r1:7b"


class TestParseSkillFile:
    def test_valid_skill(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: test-skill\n"
            "description: A test skill\n"
            "metadata:\n"
            "  tools: writer\n"
            "  model: custom-model\n"
            "---\n\n"
            "Specialist instructions here."
        )
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.tools is WRITER_TOOLS
        assert skill.preferred_model == "custom-model"
        assert skill.system_prompt == "Specialist instructions here."

    def test_missing_frontmatter(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("Just instructions, no frontmatter.")
        assert _parse_skill_file(skill_file) is None

    def test_missing_name(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\ndescription: No name\n---\n\nBody")
        assert _parse_skill_file(skill_file) is None

    def test_default_tools_is_read_only(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: minimal\ndescription: Minimal\n---\n\nBody")
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.tools is READ_ONLY_TOOLS

    def test_no_preferred_model_is_none(self, tmp_path):
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text("---\nname: simple\ndescription: Simple\n---\n\nBody")
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.preferred_model is None

    def test_reviewer_tools_resolved(self, tmp_path):
        """Skill with tools: reviewer resolves to REVIEWER_TOOLS."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: rv-skill\n"
            "description: Reviewer skill\n"
            "metadata:\n"
            "  tools: reviewer\n"
            "---\n\n"
            "Body."
        )
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.tools is REVIEWER_TOOLS


class TestLoadSkillMetadata:
    def test_returns_name_and_description(self):
        metadata = load_skill_metadata()
        names = {m["name"] for m in metadata}
        assert "code-writer" in names
        assert "code-reviewer" in names
        for m in metadata:
            assert "name" in m
            assert "description" in m


class TestFormatAvailableSkillsBlock:
    def test_formats_xml(self):
        metadata = [
            {"name": "code-writer", "description": "Write code"},
            {"name": "code-reviewer", "description": "Review code"},
        ]
        result = format_available_skills_block(metadata)
        assert "<available_skills>" in result
        assert "</available_skills>" in result
        assert "**code-writer**" in result
        assert "**code-reviewer**" in result

    def test_empty_skills(self):
        result = format_available_skills_block([])
        assert "No skills available" in result


class TestParseSimpleYaml:
    def test_simple_key_value(self):
        result = _parse_simple_yaml("name: test\ndescription: A test")
        assert result["name"] == "test"
        assert result["description"] == "A test"

    def test_block_scalar(self):
        result = _parse_simple_yaml("description: >\n  line one\n  line two")
        assert "line one" in result["description"]
        assert "line two" in result["description"]

    def test_nested_metadata(self):
        result = _parse_simple_yaml("metadata:\n  tools: writer\n  model: custom")
        assert result["metadata"]["tools"] == "writer"
        assert result["metadata"]["model"] == "custom"

    def test_mixed(self):
        yaml_text = "name: test\ndescription: A test\nmetadata:\n  tools: read-only"
        result = _parse_simple_yaml(yaml_text)
        assert result["name"] == "test"
        assert result["metadata"]["tools"] == "read-only"
