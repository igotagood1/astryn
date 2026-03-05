from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field


class ProviderUnavailable(Exception):
    """Raised when an LLM provider cannot fulfil a request.

    The caller should fall back to an alternative provider.
    """


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict | None = None

    def to_message(self) -> dict:
        """Convert to a message dict for the conversation history."""
        msg = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            msg["tool_calls"] = self.tool_calls
        return msg


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> LLMResponse: ...

    @abstractmethod
    async def is_available(self) -> bool: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    async def chat_stream(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> AsyncGenerator[str | LLMResponse, None]:
        """Yield text deltas as strings, then yield the final LLMResponse.

        Default implementation falls back to non-streaming chat().
        Override in subclasses for true token-by-token streaming.
        """
        response = await self.chat(messages, system, temperature, tools)
        if response.content:
            yield response.content
        yield response
