"""Tests for services/preferences.py — validation and formatting."""

import pytest

from services.preferences import format_preferences_block, validate_preference
from store.domain import CommunicationPreferences


class TestValidatePreference:
    def test_valid_verbosity(self):
        assert validate_preference("verbosity", "concise") == "concise"
        assert validate_preference("verbosity", "balanced") == "balanced"
        assert validate_preference("verbosity", "detailed") == "detailed"

    def test_invalid_verbosity(self):
        with pytest.raises(ValueError, match="Invalid value for verbosity"):
            validate_preference("verbosity", "verbose")

    def test_valid_tone(self):
        assert validate_preference("tone", "casual") == "casual"
        assert validate_preference("tone", "professional") == "professional"

    def test_invalid_tone(self):
        with pytest.raises(ValueError, match="Invalid value for tone"):
            validate_preference("tone", "friendly")

    def test_valid_code_explanation(self):
        assert validate_preference("code_explanation", "minimal") == "minimal"
        assert validate_preference("code_explanation", "explain") == "explain"
        assert validate_preference("code_explanation", "teach") == "teach"

    def test_invalid_code_explanation(self):
        with pytest.raises(ValueError, match="Invalid value for code_explanation"):
            validate_preference("code_explanation", "verbose")

    def test_proactive_suggestions_bool(self):
        assert validate_preference("proactive_suggestions", True) is True
        assert validate_preference("proactive_suggestions", False) is False

    def test_proactive_suggestions_string(self):
        assert validate_preference("proactive_suggestions", "true") is True
        assert validate_preference("proactive_suggestions", "yes") is True
        assert validate_preference("proactive_suggestions", "on") is True
        assert validate_preference("proactive_suggestions", "1") is True
        assert validate_preference("proactive_suggestions", "false") is False
        assert validate_preference("proactive_suggestions", "no") is False
        assert validate_preference("proactive_suggestions", "off") is False
        assert validate_preference("proactive_suggestions", "0") is False

    def test_proactive_suggestions_invalid_string(self):
        with pytest.raises(ValueError, match="Expected true/false"):
            validate_preference("proactive_suggestions", "maybe")

    def test_unknown_field(self):
        with pytest.raises(ValueError, match="Unknown preference field"):
            validate_preference("unknown_field", "value")


class TestFormatPreferencesBlock:
    def test_defaults(self):
        prefs = CommunicationPreferences()
        block = format_preferences_block(prefs)
        assert "Balanced responses" in block
        assert "Casual tone" in block
        assert "Explain code changes" in block
        assert "Proactively suggest" in block

    def test_concise(self):
        prefs = CommunicationPreferences(verbosity="concise")
        block = format_preferences_block(prefs)
        assert "Be concise" in block

    def test_detailed(self):
        prefs = CommunicationPreferences(verbosity="detailed")
        block = format_preferences_block(prefs)
        assert "Be thorough" in block

    def test_professional_tone(self):
        prefs = CommunicationPreferences(tone="professional")
        block = format_preferences_block(prefs)
        assert "Professional tone" in block

    def test_minimal_code(self):
        prefs = CommunicationPreferences(code_explanation="minimal")
        block = format_preferences_block(prefs)
        assert "Minimal code" in block

    def test_teach_mode(self):
        prefs = CommunicationPreferences(code_explanation="teach")
        block = format_preferences_block(prefs)
        assert "Teach mode" in block

    def test_no_proactive(self):
        prefs = CommunicationPreferences(proactive_suggestions=False)
        block = format_preferences_block(prefs)
        assert "Only act on what is explicitly asked" in block

    def test_all_non_default(self):
        prefs = CommunicationPreferences(
            verbosity="concise",
            tone="professional",
            code_explanation="minimal",
            proactive_suggestions=False,
        )
        block = format_preferences_block(prefs)
        assert "Be concise" in block
        assert "Professional tone" in block
        assert "Minimal code" in block
        assert "Only act on what is explicitly asked" in block

    def test_block_has_four_lines(self):
        prefs = CommunicationPreferences()
        block = format_preferences_block(prefs)
        lines = [line for line in block.strip().split("\n") if line.strip()]
        assert len(lines) == 4
