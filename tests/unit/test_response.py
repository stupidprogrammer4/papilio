from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from httpx import ASGITransport, AsyncClient, Response
from pydantic import BaseModel, ValidationError, field_validator

from papilio.api.responses.envelope import APIResponse
from papilio.api.responses.handlers import setup_exception_handlers
from papilio.errors.base import APPException
from papilio.errors.exceptions import (
    ConflictException,
    TooManyRequestsException,
    ValidationException,
)


class Payload(BaseModel):
    value: int


class Input(BaseModel):
    value: str

    @field_validator("value")
    @classmethod
    def reject(cls, value: str) -> str:
        raise ValueError("refused")


def test_response_accepts_any_pydantic_payload_and_omits_empty_envelope() -> (
    None
):
    response = APIResponse[Payload, None].from_data(Payload(value=3))

    assert response.model_dump(mode="json") == {
        "success": True,
        "data": {"value": 3},
    }


def test_validation_context_is_json_readable() -> None:
    try:
        Input(value="bad")
    except ValidationError as error:
        refused = RequestValidationError(
            [{**row, "loc": ("body", *row["loc"])} for row in error.errors()]
        )
    response = APIResponse.from_pydantic_error(refused)

    dumped = response.model_dump(mode="json")
    assert dumped["errors"][0]["loc"] == ["value"]
    assert all(
        isinstance(value, (str, int, float, bool, type(None)))
        for value in dumped["errors"][0].get("ctx", {}).values()
    )


async def _error_response(error: APPException) -> Response:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/error")
    async def fail():
        raise error

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.get("/error")


@pytest.mark.parametrize("kind", ["validation", "conflict"])
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Decimal("9007199254740993.123450"), "9007199254740993.123450"),
        (date(2026, 9, 17), "2026-09-17"),
        (
            datetime(2026, 9, 17, 12, 34, 56, 123456, tzinfo=UTC),
            "2026-09-17T12:34:56.123456Z",
        ),
        (
            UUID("12345678-1234-5678-1234-567812345678"),
            "12345678-1234-5678-1234-567812345678",
        ),
        (
            {"values": [None, False, 0, 1.5, "text"]},
            {"values": [None, False, 0, 1.5, "text"]},
        ),
    ],
    ids=["decimal", "date", "datetime", "uuid", "json-values"],
)
async def test_application_errors_preserve_status_and_json_values(
    kind, value, expected
) -> None:
    if kind == "validation":
        error = ValidationException(
            "Invalid value", "value.invalid", ["value"], input=value
        )
        status = 400
        details = {"loc": ["value"], "input": expected}
    else:
        error = ConflictException(
            "Invalid value", "value.invalid", {"value": value}
        )
        status = 409
        details = {"unique_dict": {"value": expected}}

    response = await _error_response(error)

    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "success": False,
        "error": {
            "message": "Invalid value",
            "message_code": "value.invalid",
            **details,
        },
    }


async def test_application_error_serializes_nested_children_and_context() -> (
    None
):
    child = ValidationException(
        "Invalid price",
        "price.invalid",
        ["items", 0, "price"],
        input={"price": Decimal("1.2300")},
        ctx={"rule": {"effective_on": date(2026, 9, 17)}},
    )
    response = await _error_response(
        ValidationException.get_invalid_input([child])
    )

    assert response.status_code == 400
    assert response.json()["error"]["errors"] == [
        {
            "message": "Invalid price",
            "message_code": "price.invalid",
            "loc": ["items", 0, "price"],
            "input": {"price": "1.2300"},
            "ctx": {"rule": {"effective_on": "2026-09-17"}},
        }
    ]
    assert child.input == {"price": Decimal("1.2300")}
    assert child.ctx == {"rule": {"effective_on": date(2026, 9, 17)}}


async def test_rate_limit_error_preserves_headers_and_body() -> None:
    response = await _error_response(
        TooManyRequestsException("Too many requests", "rate.limited", 5, 0, 30)
    )

    assert response.status_code == 429
    assert response.headers["retry-after"] == "30"
    assert response.headers["ratelimit-limit"] == "5"
    assert response.headers["ratelimit-remaining"] == "0"
    assert response.json() == {
        "success": False,
        "error": {
            "message": "Too many requests",
            "message_code": "rate.limited",
            "limit": 5,
            "remaining": 0,
            "retry_after": 30,
        },
    }


@pytest.mark.parametrize("success", [True, False])
def test_null_root_data_is_omitted(success: bool) -> None:
    response = APIResponse[Payload, None](success=success, data=None)
    assert response.model_dump(mode="json") == {"success": success}


def test_null_from_data_omits_all_empty_root_fields() -> None:
    response = APIResponse[None, None].from_data(None)
    assert response.model_dump(mode="json") == {"success": True}
    assert response.model_dump_json() == '{"success":true}'


def test_empty_data_collection_and_empty_message_are_preserved() -> None:
    response = APIResponse[Payload, None].from_data([], message_code="")
    assert response.model_dump(mode="json") == {
        "success": True,
        "data": [],
        "message_code": "",
    }


class NullablePayload(BaseModel):
    value: int | None
    active: bool
    items: list[int | None]


class NullableMetadata(BaseModel):
    cursor: str | None


@pytest.mark.parametrize("with_data", [True, False])
async def test_native_http_omits_root_nulls_and_preserves_nested_nulls(
    with_data: bool,
) -> None:
    app = FastAPI()

    @app.get(
        "/response",
        response_model=APIResponse[NullablePayload, NullableMetadata],
    )
    async def response() -> APIResponse[NullablePayload, NullableMetadata]:
        data = None
        if with_data:
            data = NullablePayload(value=None, active=False, items=[None, 0])
        return APIResponse[NullablePayload, NullableMetadata](
            success=True,
            data=data,
            meta=NullableMetadata(cursor=None),
        )

    async with AsyncClient(
        transport=ASGITransport(app),
        base_url="http://test",
    ) as client:
        result = await client.get("/response")
    expected: dict[str, object] = {"success": True, "meta": {"cursor": None}}
    if with_data:
        expected["data"] = {"value": None, "active": False, "items": [None, 0]}
    assert result.status_code == 200
    assert result.json() == expected
