import uuid

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

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]

    async def pull_model(self, model: str) -> str:
        """Pull a model from the Ollama registry. Returns status message."""
        async with httpx.AsyncClient(timeout=600) as client:
            r = await client.post(
                f"{self.base_url}/api/pull",
                json={"name": model, "stream": False},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("status", "success")

    async def chat(
        self,
        messages: list[dict],
        system: str,
        temperature: float = 0.7,
        tools: list[dict] | None = None,
    ) -> LLMResponse:
        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools

        async with httpx.AsyncClient(timeout=120) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()

        msg = data["message"]
        raw_tool_calls = msg.get("tool_calls") or []

        # Normalize tool calls: ensure each has an id, and arguments is always a dict.
        # Ollama omits the id field; we generate one so the rest of the system can
        # match tool results back to calls when/if we add OpenAI support later.
        tool_calls = [
            {
                "id": tc.get("id") or str(uuid.uuid4()),
                "function": {
                    "name": tc.get("function", {}).get("name", ""),
                    "arguments": tc.get("function", {}).get("arguments", {}),
                },
            }
            for tc in raw_tool_calls
        ]

        return LLMResponse(
            content=msg.get("content") or "",
            model=self._model,
            provider="ollama",
            tool_calls=tool_calls,
        )
