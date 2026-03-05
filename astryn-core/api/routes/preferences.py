"""Preferences routes — GET/POST /preferences/{session_id}."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

import services.preferences as preferences_service
from api.deps import verify_api_key
from api.schemas import PreferencesResponse, UpdatePreferenceRequest
from db.engine import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/preferences/{session_id}",
    response_model=PreferencesResponse,
    dependencies=[Depends(verify_api_key)],
)
async def get_preferences(session_id: str, db: AsyncSession = Depends(get_db)):
    prefs = await preferences_service.get_preferences(db, session_id)
    return PreferencesResponse(
        verbosity=prefs.verbosity,
        tone=prefs.tone,
        code_explanation=prefs.code_explanation,
        proactive_suggestions=prefs.proactive_suggestions,
    )


@router.post(
    "/preferences/{session_id}",
    response_model=PreferencesResponse,
    dependencies=[Depends(verify_api_key)],
)
async def update_preference(
    session_id: str,
    req: UpdatePreferenceRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        prefs = await preferences_service.update_preference(db, session_id, req.field, req.value)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return PreferencesResponse(
        verbosity=prefs.verbosity,
        tone=prefs.tone,
        code_explanation=prefs.code_explanation,
        proactive_suggestions=prefs.proactive_suggestions,
    )
