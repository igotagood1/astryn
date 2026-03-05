"""Tests for llm/skills.py — skill discovery, parsing, and formatting."""

from llm.skills import (
    SkillDef,
    _parse_simple_yaml,
    _parse_skill_file,
    discover_skills,
    format_available_skills_block,
    load_skill_metadata,
)
from tools.registry import READ_ONLY_TOOLS, READ_WRITE_TOOLS, TOOLS


class TestDiscoverSkills:
    def test_discovers_builtin_skills(self):
        skills = discover_skills()
        assert "code" in skills
        assert "explore" in skills
        assert "plan" in skills

    def test_all_are_skill_def(self):
        skills = discover_skills()
        for skill in skills.values():
            assert isinstance(skill, SkillDef)

    def test_code_has_full_tools(self):
        skills = discover_skills()
        assert skills["code"].tools is TOOLS

    def test_explore_has_read_only_tools(self):
        skills = discover_skills()
        assert skills["explore"].tools is READ_ONLY_TOOLS

    def test_plan_has_read_only_tools(self):
        skills = discover_skills()
        assert skills["plan"].tools is READ_ONLY_TOOLS

    def test_skill_prompts_are_nonempty(self):
        skills = discover_skills()
        for skill in skills.values():
            assert len(skill.system_prompt) > 50

    def test_code_prompt_content(self):
        skills = discover_skills()
        assert "code specialist" in skills["code"].system_prompt.lower()

    def test_explore_prompt_content(self):
        skills = discover_skills()
        assert "explore specialist" in skills["explore"].system_prompt.lower()

    def test_plan_prompt_content(self):
        skills = discover_skills()
        assert "plan specialist" in skills["plan"].system_prompt.lower()

    def test_discovers_review_skills(self):
        skills = discover_skills()
        assert "code-review" in skills
        assert "design-review" in skills
        assert "security-review" in skills

    def test_discovers_test_writer_skill(self):
        skills = discover_skills()
        assert "test-writer" in skills

    def test_review_skills_have_read_only_tools(self):
        skills = discover_skills()
        assert skills["code-review"].tools is READ_ONLY_TOOLS
        assert skills["design-review"].tools is READ_ONLY_TOOLS
        assert skills["security-review"].tools is READ_ONLY_TOOLS

    def test_test_writer_has_read_write_tools(self):
        skills = discover_skills()
        assert skills["test-writer"].tools is READ_WRITE_TOOLS

    def test_code_review_prompt_content(self):
        skills = discover_skills()
        assert "code review" in skills["code-review"].system_prompt.lower()

    def test_design_review_prompt_content(self):
        skills = discover_skills()
        assert "architect" in skills["design-review"].system_prompt.lower()

    def test_security_review_prompt_content(self):
        skills = discover_skills()
        assert "security" in skills["security-review"].system_prompt.lower()

    def test_test_writer_prompt_content(self):
        skills = discover_skills()
        assert "test" in skills["test-writer"].system_prompt.lower()


class TestUserSkillOverrides:
    def test_user_skill_overrides_builtin(self, tmp_path):
        """User skills with same name override built-in skills."""
        skill_dir = tmp_path / "my-code"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: code\n"
            "description: Custom code skill\n"
            "metadata:\n"
            "  tools: read-only\n"
            "---\n\n"
            "Custom code instructions."
        )

        skills = discover_skills([tmp_path])
        assert skills["code"].description == "Custom code skill"
        assert skills["code"].tools is READ_ONLY_TOOLS

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
            "  tools: full\n"
            "  model: custom-model\n"
            "---\n\n"
            "Specialist instructions here."
        )
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.name == "test-skill"
        assert skill.description == "A test skill"
        assert skill.tools is TOOLS
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

    def test_read_write_tools_resolved(self, tmp_path):
        """Skill with tools: read-write resolves to READ_WRITE_TOOLS."""
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\n"
            "name: rw-skill\n"
            "description: Read-write skill\n"
            "metadata:\n"
            "  tools: read-write\n"
            "---\n\n"
            "Body."
        )
        skill = _parse_skill_file(skill_file)
        assert skill is not None
        assert skill.tools is READ_WRITE_TOOLS


class TestLoadSkillMetadata:
    def test_returns_name_and_description(self):
        metadata = load_skill_metadata()
        names = {m["name"] for m in metadata}
        assert "code" in names
        assert "explore" in names
        assert "plan" in names
        for m in metadata:
            assert "name" in m
            assert "description" in m


class TestFormatAvailableSkillsBlock:
    def test_formats_xml(self):
        metadata = [
            {"name": "code", "description": "Write code"},
            {"name": "explore", "description": "Browse files"},
        ]
        result = format_available_skills_block(metadata)
        assert "<available_skills>" in result
        assert "</available_skills>" in result
        assert "**code**" in result
        assert "**explore**" in result

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
        result = _parse_simple_yaml("metadata:\n  tools: full\n  model: custom")
        assert result["metadata"]["tools"] == "full"
        assert result["metadata"]["model"] == "custom"

    def test_mixed(self):
        yaml_text = "name: test\ndescription: A test\nmetadata:\n  tools: read-only"
        result = _parse_simple_yaml(yaml_text)
        assert result["name"] == "test"
        assert result["metadata"]["tools"] == "read-only"
