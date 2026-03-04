import logging

from fastapi import Header, HTTPException

from llm.config import settings

logger = logging.getLogger(__name__)


def verify_api_key(x_api_key: str = Header(...)) -> None:
    """FastAPI dependency that validates the X-Api-Key request header.

    Apply to any route that should be protected:
        @router.post("/route", dependencies=[Depends(verify_api_key)])

    Raises HTTP 401 if the key is missing or incorrect.
    """
    if x_api_key != settings.astryn_api_key:
        logger.warning("Rejected request with invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")
