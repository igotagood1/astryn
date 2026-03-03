from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str
    tool_calls: list[dict] = field(default_factory=list)

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
