import logging

from fastapi import APIRouter, Depends, HTTPException

import services.session as session_service
from api.deps import verify_api_key
from api.schemas import SetProjectRequest
from tools.safety import REPOS_ROOT, SecurityError, validate_path

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/projects", dependencies=[Depends(verify_api_key)])
async def list_projects() -> list[str]:
    """Return all top-level project directories in ~/repos."""
    projects = [
        d.name for d in REPOS_ROOT.iterdir() if d.is_dir() and not d.name.startswith(".")
    ]
    return sorted(projects)


@router.post("/project/set", dependencies=[Depends(verify_api_key)])
async def set_project(req: SetProjectRequest) -> dict:
    """Set the active project for a session directly, without an LLM roundtrip."""
    try:
        path = validate_path(req.name)
    except SecurityError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not path.is_dir():
        raise HTTPException(status_code=404, detail=f"'{req.name}' is not a project in ~/repos.")

    session = session_service.get_or_create(req.session_id)
    session.state.active_project = req.name
    logger.info("Project set directly: session=%s project=%s", req.session_id, req.name)
    return {"active_project": req.name}
