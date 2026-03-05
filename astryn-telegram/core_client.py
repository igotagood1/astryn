import httpx

import config

CORE_URL = config.ASTRYN_CORE_URL
API_KEY = config.ASTRYN_CORE_API_KEY

_client: httpx.AsyncClient | None = None


class CoreError(Exception):
    """Raised when astryn-core returns an error with a user-friendly message."""


def get_client() -> httpx.AsyncClient:
    """Return the shared HTTP client, creating it on first use."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=CORE_URL,
            headers={"X-Api-Key": API_KEY},
            timeout=120,
        )
    return _client


async def close_client() -> None:
    """Close the shared HTTP client. Call on bot shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


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
    client = get_client()
    r = await client.post(
        "/chat",
        json={"message": message, "session_id": session_id},
    )
    _raise_for_status(r)
    return r.json()


async def confirm_tool(confirmation_id: str, approved: bool) -> dict:
    action = "approve" if approved else "reject"
    client = get_client()
    r = await client.post(
        f"/confirm/{confirmation_id}",
        json={"action": action},
    )
    _raise_for_status(r)
    return r.json()


async def clear_session(session_id: str) -> None:
    client = get_client()
    r = await client.delete(f"/chat/{session_id}", timeout=10)
    _raise_for_status(r)


async def get_projects() -> list[str]:
    client = get_client()
    r = await client.get("/projects", timeout=10)
    _raise_for_status(r)
    return r.json()


async def set_project_direct(name: str, session_id: str) -> dict:
    client = get_client()
    r = await client.post(
        "/project/set",
        json={"name": name, "session_id": session_id},
        timeout=10,
    )
    _raise_for_status(r)
    return r.json()


async def health_check() -> dict:
    client = get_client()
    r = await client.get("/health", timeout=5)
    _raise_for_status(r)
    return r.json()


async def list_models() -> dict:
    client = get_client()
    r = await client.get("/models", timeout=10)
    _raise_for_status(r)
    return r.json()


async def set_model(model: str) -> dict:
    client = get_client()
    r = await client.post(
        "/models/active",
        json={"model": model},
        timeout=10,
    )
    _raise_for_status(r)
    return r.json()


async def pull_model(model: str) -> dict:
    client = get_client()
    r = await client.post(
        "/models/pull",
        json={"model": model},
        timeout=600,
    )
    _raise_for_status(r)
    return r.json()


async def get_preferences(session_id: str) -> dict:
    client = get_client()
    r = await client.get(f"/preferences/{session_id}", timeout=10)
    _raise_for_status(r)
    return r.json()


async def update_preference(session_id: str, field: str, value) -> dict:
    client = get_client()
    r = await client.post(
        f"/preferences/{session_id}",
        json={"field": field, "value": value},
        timeout=10,
    )
    _raise_for_status(r)
    return r.json()
