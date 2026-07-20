from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from quant_lab import __version__
from quant_lab.api.schemas import (
    ComponentHealthResponse,
    LivenessResponse,
    ReadinessResponse,
)
from quant_lab.health.service import HealthService

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=LivenessResponse)
def liveness() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def readiness(request: Request) -> ReadinessResponse | JSONResponse:
    service: HealthService = request.app.state.health_service
    result = service.readiness()
    response = ReadinessResponse(
        status="ready" if result.ready else "not_ready",
        application_version=__version__,
        run_mode="RESEARCH",
        components=tuple(
            ComponentHealthResponse(
                name=component.name,
                status=component.status,
                message=component.message,
            )
            for component in result.components
        ),
    )
    if not result.ready:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=response.model_dump(mode="json"),
        )
    return response
