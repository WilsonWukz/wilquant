from typing import Literal

from pydantic import BaseModel, ConfigDict


class LivenessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["alive"] = "alive"


class ComponentHealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: Literal["sqlite", "duckdb"]
    status: Literal["healthy", "unhealthy"]
    message: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: Literal["ready", "not_ready"]
    application_version: str
    run_mode: Literal["RESEARCH"]
    components: tuple[ComponentHealthResponse, ...]
