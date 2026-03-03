import httpx
import os
from dotenv import load_dotenv

load_dotenv()

CORE_URL = os.getenv('ASTRYN_CORE_URL', 'http://localhost:8000')
API_KEY = os.getenv('ASTRYN_CORE_API_KEY', 'dev-key')


async def send_message(message: str, session_id: str) -> dict:
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f'{CORE_URL}/chat',
            json={'message': message, 'session_id': session_id},
            headers={'X-Api-Key': API_KEY},
        )
        r.raise_for_status()
        return r.json()


async def clear_session(session_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(
            f'{CORE_URL}/chat/{session_id}',
            headers={'X-Api-Key': API_KEY},
        )


async def health_check() -> dict:
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.get(f'{CORE_URL}/health')
        return r.json()