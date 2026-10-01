import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from app.api.schemas import ErrorDetail, ErrorResponse, FieldError

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


def unexpected_error_response(request: Request, exc: Exception) -> JSONResponse:
    # Do not log exception text or traceback: upstream errors may contain secrets.
    logger.error(
        "Unhandled request error: request_id=%s exception_type=%s",
        getattr(request.state, "request_id", "unknown"),
        type(exc).__name__,
    )
    return error_response(request, 500, "INTERNAL_ERROR", "服务暂时无法处理请求")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    fields: list[FieldError] | None = None,
    headers: dict[str, str] | None = None,
    retryable: bool | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", str(uuid4()))
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            field_errors=fields or [],
            retryable=(status_code >= 500 or status_code == 429)
            if retryable is None
            else retryable,
        ),
        request_id=request_id,
    )
    return JSONResponse(
        body.model_dump(),
        status_code=status_code,
        headers={**(headers or {}), "X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(
            request, exc.status_code, exc.code, exc.message, retryable=exc.retryable
        )

    @app.exception_handler(HTTPException)
    async def handle_http_error(request: Request, exc: HTTPException) -> JSONResponse:
        # Never return arbitrary exception detail: it may contain provider data.
        messages = {404: "资源不存在", 405: "请求方法不支持"}
        return error_response(
            request,
            exc.status_code,
            f"HTTP_{exc.status_code}",
            messages.get(exc.status_code, "请求无法完成"),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            request,
            422,
            "VALIDATION_ERROR",
            "请求参数不合法",
            fields=[
                FieldError(field=".".join(map(str, item["loc"])), message="字段格式或取值不合法")
                for item in exc.errors()
            ],
        )
