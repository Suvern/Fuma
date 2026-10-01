from fastapi import APIRouter, Request, Response

from app.api.schemas import DependencyChecks, LivenessResponse, ReadinessResponse
from app.infrastructure.health import check_dependencies

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", operation_id="get_liveness", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    """Process liveness only; does not imply integrations or business features are ready."""
    return LivenessResponse()


@router.get(
    "/ready",
    operation_id="get_readiness",
    response_model=ReadinessResponse,
    responses={503: {"model": ReadinessResponse, "description": "Dependency unavailable"}},
)
def readiness(request: Request, response: Response) -> ReadinessResponse:
    """Check connectivity only, without disclosing connection strings or errors."""
    checks: DependencyChecks = check_dependencies(request.app.state.engine, request.app.state.redis)
    ready = checks.database == "ok" and checks.redis == "ok"
    response.status_code = 200 if ready else 503
    return ReadinessResponse(status="ok" if ready else "degraded", checks=checks)
