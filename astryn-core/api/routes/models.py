import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import verify_api_key
from api.schemas import SetModelRequest
from llm.router import get_active_model, list_available_models, set_active_model

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models", dependencies=[Depends(verify_api_key)])
async def get_models():
    models = await list_available_models()
    return {"models": models, "active": get_active_model()}


@router.post("/models/active", dependencies=[Depends(verify_api_key)])
async def set_active(req: SetModelRequest):
    available = await list_available_models()
    if req.model not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{req.model}' not found. Available: {available}",
        )
    set_active_model(req.model)
    logger.info("Active model switched to: %s", req.model)
    return {"active": req.model}
