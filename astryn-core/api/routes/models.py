import logging

from fastapi import APIRouter, Depends, HTTPException

from api.deps import verify_api_key
from api.schemas import PullModelRequest, SetModelRequest
from llm.config import settings
from llm.providers.ollama import OllamaProvider
from llm.router import get_active_model, list_available_models, set_active_model

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/models", dependencies=[Depends(verify_api_key)])
async def get_models():
    models = await list_available_models()
    return {
        "models": models,
        "active": get_active_model(),
        "coordinator": {
            "provider": settings.astryn_coordinator_provider,
            "model": settings.astryn_coordinator_model,
        },
        "specialist": {
            "model": settings.astryn_specialist_model,
        },
    }


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


@router.post("/models/pull", dependencies=[Depends(verify_api_key)])
async def pull_model(req: PullModelRequest):
    """Pull a model from the Ollama registry. This may take several minutes."""
    ollama = OllamaProvider(base_url=settings.ollama_base_url, model=req.model)

    if not await ollama.is_available():
        raise HTTPException(status_code=503, detail="Ollama is not available.")

    logger.info("Pulling model: %s", req.model)
    try:
        status = await ollama.pull_model(req.model)
    except Exception as e:
        logger.error("Model pull failed: %s error=%s", req.model, e)
        raise HTTPException(status_code=500, detail=f"Pull failed: {e}") from e

    logger.info("Model pulled: %s status=%s", req.model, status)
    return {"model": req.model, "status": status}
