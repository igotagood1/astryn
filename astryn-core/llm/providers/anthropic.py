"""Anthropic LLM provider — Claude models via the Anthropic API.

Format conversion happens at the boundary: internal message format is
OpenAI-style dicts; this provider converts to/from Anthropic's format.
"""

import logging
import uuid

from llm.base import LLMProvider, LLMResponse, ProviderUnavailable

logger = logging.getLogger(__name__)


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str, max_tokens: int = 4096):
        self._api_key = api_key
        self._model = model
        self._max_tokens = max_tokens
        self._client = None

    def _get_client(self):
        """Lazy-import and instantiate the Anthropic client."""
        if self._client is None:
            import anthropic

            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    @property
    def model_name(self) -> str:
        return f"anthropic/{self._model}"

    async def is_available(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list(limit=1)
            return True
        except Exception as e:
            logger.warning("Anthropic API unavailable: %s", e)
            return False

    async def chat(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        try:
            import anthropic as anthropic_mod
        except ImportError as e:
            raise ProviderUnavailable("anthropic package not installed") from e

        client = self._get_client()
        anthropic_messages = _to_anthropic_messages(messages)
        kwargs: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": anthropic_messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = _to_anthropic_tools(tools)

        try:
            response = await client.messages.create(**kwargs)
        except anthropic_mod.RateLimitError as e:
            raise ProviderUnavailable(f"Anthropic rate limit: {e}") from e
        except anthropic_mod.APIConnectionError as e:
            raise ProviderUnavailable(f"Anthropic connection error: {e}") from e
        except anthropic_mod.APIStatusError as e:
            raise ProviderUnavailable(f"Anthropic API error ({e.status_code}): {e}") from e

        return _from_anthropic_response(response, self._model)


def _to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert OpenAI-style messages to Anthropic format.

    Key differences:
    - Anthropic has no "system" role in messages (passed separately)
    - Tool results are sent as user messages with tool_result content blocks
    - Consecutive tool results must be merged into a single user message
    - Assistant messages with tool_calls become content blocks with tool_use type
    """
    result = []
    for msg in messages:
        role = msg.get("role", "")

        if role == "system":
            # Skip — system is passed separately to Anthropic
            continue

        if role == "tool":
            # Tool results become user messages with tool_result content blocks
            block = {
                "type": "tool_result",
                "tool_use_id": msg["tool_call_id"],
                "content": msg.get("content", ""),
            }
            # Merge consecutive tool results into one user message
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], list):
                result[-1]["content"].append(block)
            else:
                result.append({"role": "user", "content": [block]})
            continue

        if role == "assistant":
            content_blocks = []
            text = msg.get("content") or ""
            if text:
                content_blocks.append({"type": "text", "text": text})

            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    import json

                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                content_blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc.get("id", str(uuid.uuid4())),
                        "name": fn.get("name", ""),
                        "input": args,
                    }
                )

            if content_blocks:
                result.append({"role": "assistant", "content": content_blocks})
            else:
                # Empty assistant message — use text block
                result.append({"role": "assistant", "content": [{"type": "text", "text": ""}]})
            continue

        if role == "user":
            content = msg.get("content", "")
            # Merge consecutive user messages
            if result and result[-1]["role"] == "user" and isinstance(result[-1]["content"], str):
                result[-1]["content"] += "\n" + content
            else:
                result.append({"role": "user", "content": content})
            continue

    return result


def _from_anthropic_response(response, model: str) -> LLMResponse:
    """Convert Anthropic response to LLMResponse with OpenAI-style tool_calls."""
    text_parts = []
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                {
                    "id": block.id,
                    "function": {
                        "name": block.name,
                        "arguments": block.input,
                    },
                }
            )

    usage = None
    if response.usage:
        usage = {
            "input_tokens": response.usage.input_tokens,
            "output_tokens": response.usage.output_tokens,
        }

    return LLMResponse(
        content="\n".join(text_parts),
        model=model,
        provider="anthropic",
        tool_calls=tool_calls,
        usage=usage,
    )


def _to_anthropic_tools(tools: list[dict]) -> list[dict]:
    """Convert OpenAI-style tool schemas to Anthropic format.

    OpenAI: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
    Anthropic: {"name": ..., "description": ..., "input_schema": ...}
    """
    result = []
    for tool in tools:
        fn = tool.get("function", {})
        result.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return result
