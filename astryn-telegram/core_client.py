import httpx

import config

CORE_URL = config.ASTRYN_CORE_URL
API_KEY = config.ASTRYN_CORE_API_KEY


class CoreError(Exception):
    """Raised when astryn-core returns an error with a user-friendly message."""


def _raise_for_status(response: httpx.Response) -> None:
    """Like raise_for_status but extracts the detail field from JSON error responses."""
    if response.is_success:
        return
    try:
        detail = response.json().get("detail")
    except (ValueError, KeyError):
        detail = None
    if detail:
        raise CoreError(detail)
    response.raise_for_status()


async def send_message(message: str, session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{CORE_URL}/chat",
            json={"message": message, "session_id": session_id},
            headers={"X-Api-Key": API_KEY},
        )
        _raise_for_status(r)
        return r.json()


async def confirm_tool(confirmation_id: str, approved: bool) -> dict:
    action = "approve" if approved else "reject"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{CORE_URL}/confirm/{confirmation_id}",
            json={"action": action},
            headers={"X-Api-Key": API_KEY},
        )
        _raise_for_status(r)
        return r.json()


async def clear_session(session_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.delete(
            f"{CORE_URL}/chat/{session_id}",
            headers={"X-Api-Key": API_KEY},
        )
        _raise_for_status(r)


async def get_projects() -> list[str]:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CORE_URL}/projects", headers={"X-Api-Key": API_KEY})
        _raise_for_status(r)
        return r.json()


async def set_project_direct(name: str, session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{CORE_URL}/project/set",
            json={"name": name, "session_id": session_id},
            headers={"X-Api-Key": API_KEY},
        )
        _raise_for_status(r)
        return r.json()


async def health_check() -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f"{CORE_URL}/health")
        _raise_for_status(r)
        return r.json()


async def list_models() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{CORE_URL}/models", headers={"X-Api-Key": API_KEY})
        _raise_for_status(r)
        return r.json()


async def set_model(model: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{CORE_URL}/models/active",
            json={"model": model},
            headers={"X-Api-Key": API_KEY},
        )
        _raise_for_status(r)
        return r.json()
