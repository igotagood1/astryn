from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel

from llm.config import settings
from llm.router import get_active_model, list_available_models, set_active_model

router = APIRouter()


class SetModelRequest(BaseModel):
    model: str


@router.get("/models")
async def get_models(x_api_key: str = Header(...)):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    models = await list_available_models()
    return {"models": models, "active": get_active_model()}


@router.post("/models/active")
async def set_active(
    req: SetModelRequest,
    x_api_key: str = Header(...),
):
    if x_api_key != settings.astryn_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    available = await list_available_models()
    if req.model not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{req.model}' not found. Available: {available}",
        )
    set_active_model(req.model)
    return {"active": req.model}
