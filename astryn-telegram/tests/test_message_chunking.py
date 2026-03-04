"""Tests for _split_message — Telegram code-block-aware chunking.

The _split_message function is pure logic (no Telegram SDK dependency),
but it lives in handlers/message.py which imports telegram at the top level.
We mock the telegram package before importing to avoid needing the SDK.
"""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

# Add the telegram service root to sys.path so we can import handlers
_telegram_root = str(Path(__file__).resolve().parent.parent)
if _telegram_root not in sys.path:
    sys.path.insert(0, _telegram_root)

# Stub out telegram and its submodules before importing handlers.message
_telegram_mock = types.ModuleType("telegram")
_telegram_mock.error = types.ModuleType("telegram.error")
_telegram_mock.error.BadRequest = type("BadRequest", (Exception,), {})
_telegram_mock.InlineKeyboardButton = MagicMock()
_telegram_mock.InlineKeyboardMarkup = MagicMock()
_telegram_mock.Message = MagicMock()
_telegram_mock.Update = MagicMock()

_telegram_ext = types.ModuleType("telegram.ext")
_telegram_ext.ContextTypes = MagicMock()

sys.modules.setdefault("telegram", _telegram_mock)
sys.modules.setdefault("telegram.error", _telegram_mock.error)
sys.modules.setdefault("telegram.ext", _telegram_ext)

# Stub config and core_client (they also import at module level)
sys.modules.setdefault("config", types.ModuleType("config"))
_core_client = types.ModuleType("core_client")
_core_client.CoreError = type("CoreError", (Exception,), {})
_core_client.send_message = MagicMock()
sys.modules.setdefault("core_client", _core_client)

# Stub handlers.commands (imported by handlers.message)
_commands = types.ModuleType("handlers.commands")
for name in ("cmd_clear", "cmd_help", "cmd_model", "cmd_projects", "cmd_status"):
    setattr(_commands, name, MagicMock())
sys.modules.setdefault("handlers.commands", _commands)

# Import the actual handlers.message (from sys.path) — need to pop any
# stale 'handlers' module reference so Python resolves the real package.
sys.modules.pop("handlers", None)
sys.modules.pop("handlers.message", None)

from handlers.message import _split_message  # noqa: E402


class TestSplitMessageBasic:
    def test_short_text_single_chunk(self):
        result = _split_message("Hello world")
        assert result == ["Hello world"]

    def test_empty_text(self):
        result = _split_message("")
        assert result == [""]

    def test_exact_limit(self):
        text = "a" * 4096
        result = _split_message(text, max_len=4096)
        assert len(result) == 1

    def test_splits_at_newlines(self):
        """Should prefer splitting at newline boundaries, not mid-line."""
        lines = ["line " + str(i) for i in range(600)]
        text = "\n".join(lines)
        result = _split_message(text, max_len=4096)
        assert len(result) > 1
        for chunk in result:
            assert len(chunk) <= 4096
        # Rejoin should give back the original
        assert "\n".join(result) == text

    def test_no_empty_chunks(self):
        text = "a\n" * 3000
        result = _split_message(text.strip(), max_len=4096)
        for chunk in result:
            assert chunk  # no empty strings


class TestSplitMessageCodeBlocks:
    def test_code_block_gets_balanced_fences(self):
        """When a code block spans a chunk boundary, each chunk should
        have balanced fences (closed in current, reopened in next)."""
        code = "```python\n" + "x = 1\n" * 800 + "```"
        result = _split_message(code, max_len=4096)
        assert len(result) > 1
        for chunk in result:
            opens = chunk.count("```")
            # Each chunk should have an even number of ``` (balanced)
            assert opens % 2 == 0, f"Unbalanced fences in chunk: {chunk[:100]}..."

    def test_language_tag_preserved_on_reopen(self):
        """When splitting inside a code block, the reopened fence should
        include the original language tag."""
        code = "```python\n" + "x = 1\n" * 800 + "```"
        result = _split_message(code, max_len=4096)
        # Second and subsequent chunks that continue a code block
        # should start with ```python
        for chunk in result[1:]:
            if chunk.lstrip().startswith("```"):
                assert chunk.lstrip().startswith("```python")

    def test_text_before_code_block(self):
        """Text + code block should both be present in output."""
        text = "Here is some code:\n```js\nconsole.log('hi')\n```"
        result = _split_message(text, max_len=4096)
        combined = "\n".join(result)
        assert "Here is some code:" in combined
        assert "console.log('hi')" in combined

    def test_no_fence_injection_on_plain_text(self):
        """Plain text (no code blocks) should not get extra fences."""
        text = "Just plain text\n" * 600
        result = _split_message(text.strip(), max_len=4096)
        for chunk in result:
            assert "```" not in chunk


class TestSplitMessageHardSplit:
    def test_no_newlines_preserves_all_chars(self):
        """When text has no newlines, a hard split must not lose any characters."""
        text = "x" * 5000
        result = _split_message(text, max_len=4096)
        assert "".join(result) == text

    def test_no_newlines_chunk_sizes(self):
        text = "a" * 6000
        result = _split_message(text, max_len=4096)
        assert len(result) == 2
        assert len(result[0]) == 4096
        assert len(result[1]) == 1904
