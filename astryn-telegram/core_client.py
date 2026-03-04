import httpx

import config

CORE_URL = config.ASTRYN_CORE_URL
API_KEY = config.ASTRYN_CORE_API_KEY


async def send_message(message: str, session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{CORE_URL}/chat",
            json={"message": message, "session_id": session_id},
            headers={"X-Api-Key": API_KEY},
        )
        r.raise_for_status()
        return r.json()


async def confirm_tool(confirmation_id: str, approved: bool) -> dict:
    action = "approve" if approved else "reject"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{CORE_URL}/confirm/{confirmation_id}",
            json={"action": action},
            headers={"X-Api-Key": API_KEY},
        )
        r.raise_for_status()
        return r.json()


async def clear_session(session_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(
            f"{CORE_URL}/chat/{session_id}",
            headers={"X-Api-Key": API_KEY},
        )


async def get_projects() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CORE_URL}/projects", headers={"X-Api-Key": API_KEY})
        r.raise_for_status()
        return r.json()


async def set_project_direct(name: str, session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{CORE_URL}/project/set",
            json={"name": name, "session_id": session_id},
            headers={"X-Api-Key": API_KEY},
        )
        r.raise_for_status()
        return r.json()


async def health_check() -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{CORE_URL}/health")
        r.raise_for_status()
        return r.json()


async def list_models() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CORE_URL}/models", headers={"X-Api-Key": API_KEY})
        r.raise_for_status()
        return r.json()


async def set_model(model: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{CORE_URL}/models/active",
            json={"model": model},
            headers={"X-Api-Key": API_KEY},
        )
        r.raise_for_status()
        return r.json()
