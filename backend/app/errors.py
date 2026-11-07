from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(HTTPException):
    """HTTP-ошибка с machine-кодом для локализации на фронтенде."""

    def __init__(self, status_code: int, code: str, detail: str | None = None):
        self.code = code
        super().__init__(status_code=status_code, detail=detail or code)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            {"detail": jsonable_encoder(exc.errors()), "code": "validation_error"},
            status_code=422,
        )
