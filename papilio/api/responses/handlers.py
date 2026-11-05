from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError as PydanticError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from papilio.core import resources
from papilio.core.logger import logger
from papilio.errors.base import APPException
from papilio.errors.exceptions import (
    NotFoundException,
    TooManyRequestsException,
)
from papilio.errors.outputs import BaseErrorOut, NotFoundErrorOut
from papilio.tools.ids import IDEncryption
from papilio.types.enums import MediaType

from .envelope import APIResponse


async def external_error_handler(
    request: Request, exc: APPException
) -> JSONResponse:
    """Serialise a typed exception into the standard envelope.

    A 429 also carries its budget as headers, so a route guard's refusal looks
    identical to the middleware's — a client should not have to parse the body
    to learn how long to wait.
    """
    response_model = APIResponse.from_external_error(exc)
    if (
        isinstance(exc, NotFoundException)
        and exc.identifier == "id"
        and not exc.identifier_is_public
        and isinstance(exc.identifier_value, int)
    ):
        encryptions: Mapping[str, IDEncryption] = request.app.extra.get(
            "papilio_id_encryptions", {}
        )
        codec = encryptions.get(exc.entity)
        if codec is not None:
            public_id = codec.encode(exc.identifier_value)
            response_model = APIResponse(
                success=False,
                error=NotFoundErrorOut(
                    message_code=exc.message_code,
                    message=(
                        f"Cannot find {exc.entity} by id "
                        f"with value {public_id}"
                    ),
                    entity=exc.entity,
                    identifier="id",
                    identifier_value=str(public_id),
                ),
            )
    headers = None
    if isinstance(exc, TooManyRequestsException):
        headers = {
            "Retry-After": str(exc.retry_after),
            "RateLimit-Limit": str(exc.limit),
            "RateLimit-Remaining": str(exc.remaining),
        }
    return JSONResponse(
        content=response_model.model_dump(mode="json", exclude_defaults=True),
        status_code=exc.status_code,
        media_type=MediaType.JSON,
        headers=headers,
    )


async def pydantic_error_handler(
    request: Request, exc: PydanticError
) -> JSONResponse:
    response_model = APIResponse.from_pydantic_error(exc)
    return JSONResponse(
        # Convert rejected values such as Decimal and dates to JSON-safe data.
        content=response_model.model_dump(mode="json", exclude_defaults=True),
        status_code=422,
        media_type=MediaType.JSON,
    )


async def http_error_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """Answer Starlette's own HTTP errors in the app's error envelope.

    An unmatched path and a wrong method never reach a router, so they are the
    two failures that would otherwise reply in Starlette's ``{"detail": ...}``
    shape — and they are the two a client hits most while finding its way
    around the API.

    Args:
        request (Request): The incoming request.
        exc (StarletteHTTPException): The raised Starlette HTTP error.
    Returns:
        (JSONResponse): The error in the standard envelope.
    """
    codes = {
        404: resources.ROUTE_NOT_FOUND,
        405: resources.METHOD_NOT_ALLOWED,
    }
    response_model = APIResponse(
        success=False,
        error=BaseErrorOut(
            message=str(exc.detail),
            message_code=codes.get(exc.status_code, resources.SERVER_ERROR),
        ),
    )
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=exc.status_code,
        # a 405 without Allow, or a 401 without WWW-Authenticate, is not the
        # status it claims to be
        headers=exc.headers,
        media_type=MediaType.JSON,
    )


def unexcepted_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # the route is half the story of a 500; log it with the traceback
    logger.error(
        "unhandled error on %s %s: %s",
        request.method,
        request.url.path,
        exc,
        exc_info=exc,
    )
    response_model = APIResponse.get_server_error()
    return JSONResponse(
        content=response_model.model_dump(exclude_defaults=True),
        status_code=500,
        media_type=MediaType.JSON,
    )


exception_handlers = {
    PydanticError: pydantic_error_handler,
    StarletteHTTPException: http_error_handler,
    APPException: external_error_handler,
    Exception: unexcepted_error_handler,
}


def setup_exception_handlers(
    app: FastAPI, *, id_encryptions: Mapping[str, IDEncryption] | None = None
) -> None:
    """Install native errors with explicitly configured public-ID entities.

    Args:
        app: Owning HTTP application.
        id_encryptions: Entity-to-codec bindings for public NotFound output;
            omitted bindings preserve the existing error representation.

    Returns:
        None. Error encoding is local to this app and leaves exceptions intact.
    """
    app.extra["papilio_id_encryptions"] = MappingProxyType(
        dict(id_encryptions or {})
    )
    for exc_class, handler in exception_handlers.items():
        app.add_exception_handler(exc_class, handler)
