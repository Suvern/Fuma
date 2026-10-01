from typing import Literal

from pydantic import BaseModel, Field


class FieldError(BaseModel):
    field: str
    message: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    retryable: bool = False


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["fuma-api"] = "fuma-api"


class DependencyChecks(BaseModel):
    database: Literal["ok", "unavailable"]
    redis: Literal["ok", "unavailable"]


class ReadinessResponse(BaseModel):
    status: Literal["ok", "degraded"]
    checks: DependencyChecks
