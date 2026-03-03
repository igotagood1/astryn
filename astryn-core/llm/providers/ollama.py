import httpx
from llm.base import LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self._model = model

    @property
    def model_name(self) -> str:
        return f"ollama/{self._model}"

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self.base_url}/api/tags", timeout=3)
                return r.status_code == 200
        except Exception:
            return False

    async def chat(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return LLMResponse(
                content=data["message"]["content"],
                model=self._model,
                provider="ollama",
            )
