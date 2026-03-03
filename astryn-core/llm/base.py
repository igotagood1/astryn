from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    provider: str


class LLMProvider(ABC):
    """Abstract base - Every LLM provider implements these methods."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
    ) -> LLMResponse: ...

    @abstractmethod
    async def is_available(self) -> bool: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...
