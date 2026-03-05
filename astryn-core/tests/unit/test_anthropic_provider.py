"""Tests for llm/providers/anthropic.py — message/tool format conversion and error handling."""

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

from llm.base import ProviderUnavailable
from llm.providers.anthropic import (
    AnthropicProvider,
    _from_anthropic_response,
    _to_anthropic_messages,
    _to_anthropic_tools,
)

# ── Format Conversion ──────────────────────────────────────────────


class TestToAnthropicMessages:
    def test_user_message(self):
        msgs = [{"role": "user", "content": "hello"}]
        result = _to_anthropic_messages(msgs)
        assert result == [{"role": "user", "content": "hello"}]

    def test_assistant_text_only(self):
        msgs = [{"role": "assistant", "content": "hi there"}]
        result = _to_anthropic_messages(msgs)
        assert result == [{"role": "assistant", "content": [{"type": "text", "text": "hi there"}]}]

    def test_assistant_with_tool_calls(self):
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "read_file",
                            "arguments": {"path": "main.py"},
                        },
                    }
                ],
            }
        ]
        result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"
        blocks = result[0]["content"]
        assert any(b["type"] == "tool_use" and b["name"] == "read_file" for b in blocks)

    def test_tool_result_as_user_message(self):
        msgs = [
            {"role": "tool", "tool_call_id": "call-1", "content": "file contents here"},
        ]
        result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert result[0]["content"][0]["type"] == "tool_result"
        assert result[0]["content"][0]["tool_use_id"] == "call-1"

    def test_consecutive_tool_results_merged(self):
        msgs = [
            {"role": "tool", "tool_call_id": "call-1", "content": "result 1"},
            {"role": "tool", "tool_call_id": "call-2", "content": "result 2"},
        ]
        result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"
        assert len(result[0]["content"]) == 2

    def test_system_messages_skipped(self):
        msgs = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
        ]
        result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "user"

    def test_string_arguments_parsed_to_dict(self):
        msgs = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path": "main.py"}',
                        },
                    }
                ],
            }
        ]
        result = _to_anthropic_messages(msgs)
        tool_block = next(b for b in result[0]["content"] if b["type"] == "tool_use")
        assert tool_block["input"] == {"path": "main.py"}

    def test_empty_assistant_message(self):
        msgs = [{"role": "assistant", "content": ""}]
        result = _to_anthropic_messages(msgs)
        assert len(result) == 1
        assert result[0]["role"] == "assistant"


class TestFromAnthropicResponse:
    def test_text_response(self):
        @dataclass
        class Usage:
            input_tokens: int = 100
            output_tokens: int = 50

        @dataclass
        class TextBlock:
            type: str = "text"
            text: str = "Hello!"

        @dataclass
        class MockResponse:
            content: list = field(default_factory=lambda: [TextBlock()])
            usage: Usage = field(default_factory=Usage)

        resp = MockResponse()
        result = _from_anthropic_response(resp, "claude-sonnet-4-6")
        assert result.content == "Hello!"
        assert result.model == "claude-sonnet-4-6"
        assert result.provider == "anthropic"
        assert result.tool_calls == []
        assert result.usage == {"input_tokens": 100, "output_tokens": 50}

    def test_tool_use_response(self):
        @dataclass
        class Usage:
            input_tokens: int = 200
            output_tokens: int = 100

        @dataclass
        class ToolUseBlock:
            type: str = "tool_use"
            id: str = "toolu_123"
            name: str = "read_file"
            input: dict = field(default_factory=lambda: {"path": "main.py"})

        @dataclass
        class MockResponse:
            content: list = field(default_factory=lambda: [ToolUseBlock()])
            usage: Usage = field(default_factory=Usage)

        resp = MockResponse()
        result = _from_anthropic_response(resp, "claude-sonnet-4-6")
        assert result.content == ""
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc["id"] == "toolu_123"
        assert tc["function"]["name"] == "read_file"
        assert tc["function"]["arguments"] == {"path": "main.py"}

    def test_mixed_text_and_tool_use(self):
        @dataclass
        class Usage:
            input_tokens: int = 200
            output_tokens: int = 100

        @dataclass
        class TextBlock:
            type: str = "text"
            text: str = "Let me read that file."

        @dataclass
        class ToolUseBlock:
            type: str = "tool_use"
            id: str = "toolu_456"
            name: str = "read_file"
            input: dict = field(default_factory=lambda: {"path": "test.py"})

        @dataclass
        class MockResponse:
            content: list = field(default_factory=lambda: [TextBlock(), ToolUseBlock()])
            usage: Usage = field(default_factory=Usage)

        resp = MockResponse()
        result = _from_anthropic_response(resp, "claude-sonnet-4-6")
        assert "Let me read that file." in result.content
        assert len(result.tool_calls) == 1


class TestToAnthropicTools:
    def test_converts_openai_format(self):
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
            }
        ]
        result = _to_anthropic_tools(tools)
        assert len(result) == 1
        assert result[0]["name"] == "read_file"
        assert result[0]["description"] == "Read a file"
        assert "properties" in result[0]["input_schema"]

    def test_empty_tools(self):
        assert _to_anthropic_tools([]) == []


# ── Provider Error Handling ─────────────────────────────────────────


class TestAnthropicProviderErrors:
    async def test_rate_limit_raises_unavailable(self):
        import anthropic

        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.RateLimitError(
                message="rate limited",
                response=AsyncMock(status_code=429, headers={}),
                body=None,
            )
        )
        provider._client = mock_client

        with pytest.raises(ProviderUnavailable, match="rate limit"):
            await provider.chat(
                messages=[{"role": "user", "content": "test"}],
                system="test",
            )

    async def test_connection_error_raises_unavailable(self):
        import anthropic

        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIConnectionError(request=AsyncMock())
        )
        provider._client = mock_client

        with pytest.raises(ProviderUnavailable, match="connection"):
            await provider.chat(
                messages=[{"role": "user", "content": "test"}],
                system="test",
            )

    async def test_api_status_error_raises_unavailable(self):
        import anthropic

        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="server error",
                response=AsyncMock(status_code=500, headers={}),
                body=None,
            )
        )
        provider._client = mock_client

        with pytest.raises(ProviderUnavailable, match="API error"):
            await provider.chat(
                messages=[{"role": "user", "content": "test"}],
                system="test",
            )


class TestAnthropicProviderModelName:
    def test_model_name(self):
        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")
        assert provider.model_name == "anthropic/claude-sonnet-4-6"


class TestAnthropicProviderSuccess:
    async def test_successful_chat(self):
        @dataclass
        class Usage:
            input_tokens: int = 100
            output_tokens: int = 50

        @dataclass
        class TextBlock:
            type: str = "text"
            text: str = "Hello!"

        @dataclass
        class MockResponse:
            content: list = field(default_factory=lambda: [TextBlock()])
            usage: Usage = field(default_factory=Usage)

        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=MockResponse())
        provider._client = mock_client

        result = await provider.chat(
            messages=[{"role": "user", "content": "hello"}],
            system="be helpful",
        )

        assert result.content == "Hello!"
        assert result.provider == "anthropic"
        assert result.usage == {"input_tokens": 100, "output_tokens": 50}

    async def test_chat_with_tools(self):
        @dataclass
        class Usage:
            input_tokens: int = 200
            output_tokens: int = 100

        @dataclass
        class ToolUseBlock:
            type: str = "tool_use"
            id: str = "toolu_123"
            name: str = "delegate"
            input: dict = field(
                default_factory=lambda: {"specialist": "code", "task": "write hello.py"}
            )

        @dataclass
        class MockResponse:
            content: list = field(default_factory=lambda: [ToolUseBlock()])
            usage: Usage = field(default_factory=Usage)

        provider = AnthropicProvider(api_key="test-key", model="claude-sonnet-4-6")
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=MockResponse())
        provider._client = mock_client

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "delegate",
                    "description": "Delegate task",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]

        result = await provider.chat(
            messages=[{"role": "user", "content": "write hello.py"}],
            system="be helpful",
            tools=tools,
        )

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0]["function"]["name"] == "delegate"
        # Verify tools were passed to Anthropic in correct format
        call_kwargs = mock_client.messages.create.call_args.kwargs
        assert "tools" in call_kwargs
        assert call_kwargs["tools"][0]["name"] == "delegate"
