"""JSON-configured public IDs work as native Pydantic field metadata."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, ValidationError

from papilio.api.dependencies.ids import decode_path_id
from papilio.api.responses.handlers import setup_exception_handlers
from papilio.core import resources
from papilio.core.encryption import get_id_encryption_settings
from papilio.errors.exceptions import NotFoundException
from papilio.schemas.inputs import BaseDTO
from papilio.schemas.outputs import BaseOutput
from papilio.types.aliases import IdType
from papilio.types.ids import IDInput, IDOutput

pytestmark = pytest.mark.unit


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    payload = json.dumps(
        {
            "accounts/users": {
                "mod": 90000,
                "coff": 7,
                "offset": 10000,
                "entity": "User",
            },
            "catalog/brands": {
                "mod": 9000,
                "coff": 11,
                "offset": 1000,
                "entity": "Brand",
            },
        }
    ).encode()
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    monkeypatch.setenv("PAPILIO_ENCRYPTION", "controlled-encryption.json")
    get_id_encryption_settings.cache_clear()
    yield
    get_id_encryption_settings.cache_clear()


def test_inputs_decode_named_fields_lists_and_nullable_references(
    configured: None,
) -> None:
    class Input(BaseDTO):
        user_id: Annotated[IdType, IDInput("accounts/users")]
        other_ids: list[Annotated[IdType, IDInput("accounts/users")]]
        reviewer_id: Annotated[IdType, IDInput("accounts/users")] | None = None

    value = Input(user_id=10294, other_ids=[10049, 10063])
    assert value.to_row() == {"user_id": 42, "other_ids": [7, 9]}
    assert value.reviewer_id is None
    with pytest.raises(ValidationError):
        Input(user_id=9999, other_ids=[])
    assert Input.model_validate(value) is value


def test_outputs_encode_any_field_without_decoding_internal_inputs(
    configured: None,
) -> None:
    class Output(BaseOutput):
        id: Annotated[int, IDOutput("accounts/users")]
        user_id: Annotated[int, IDOutput("accounts/users")]
        user_ids: list[Annotated[int, IDOutput("accounts/users")]]
        reviewer_id: Annotated[int, IDOutput("accounts/users")] | None = None
        brand_id: Annotated[int, IDOutput("catalog/brands")]

    value = Output.from_dict(
        {"id": 42, "user_id": 7, "user_ids": [7, 9], "brand_id": 3}
    )
    assert value.id == 42 and value.user_id == 7
    assert value.model_dump(mode="json") == {
        "id": 10294,
        "user_id": 10049,
        "user_ids": [10049, 10063],
        "reviewer_id": None,
        "brand_id": 1033,
    }


def test_plain_fields_and_models_remain_unencoded(configured: None) -> None:
    class Plain(BaseModel):
        id: int

    assert Plain(id=42).model_dump() == {"id": 42}
    assert get_id_encryption_settings().entities["User"].encode(42) == 10294
    with pytest.raises(KeyError):
        IDInput("missing/resource")


async def test_http_paths_queries_body_and_not_found_share_configured_ids(
    configured: None,
) -> None:
    class Input(BaseDTO):
        user_id: Annotated[IdType, IDInput("accounts/users")]

    class Output(BaseOutput):
        user_id: Annotated[int, IDOutput("accounts/users")]

    app = FastAPI()
    setup_exception_handlers(
        app, id_encryptions=get_id_encryption_settings().entities
    )
    received: list[tuple[int, int]] = []

    @app.post("/references/{user_id}")
    async def reference(
        user_id: Annotated[IdType, IDInput("accounts/users")], data: Input
    ) -> Output:
        received.append((user_id, data.user_id))
        return Output(user_id=data.user_id)

    @app.get("/references")
    async def query(
        user_id: Annotated[IdType, IDInput("accounts/users")],
    ) -> Output:
        return Output(user_id=user_id)

    error = NotFoundException(
        entity="User",
        identifier="id",
        identifier_value=42,
        message="Cannot find User by id with value 42",
        message_code=resources.NOT_FOUND_ERROR,
    )

    @app.get("/missing")
    async def missing() -> None:
        raise error

    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/references/10049", json={"user_id": 10063}
        )
        assert response.status_code == 200 and response.json() == {
            "user_id": 10063
        }
        assert received == [(7, 9)]
        assert (
            await client.get("/references", params={"user_id": 10294})
        ).json() == {"user_id": 10294}
        assert (
            await client.post("/references/9999", json={"user_id": 10049})
        ).status_code == 422
        response = await client.get("/missing")
        assert response.status_code == 404
        assert response.json()["error"]["identifier_value"] == "10294"
        assert (
            response.json()["error"]["message"]
            == "Cannot find User by id with value 10294"
        )
    assert error.identifier_value == 42 and error.message.endswith("42")


async def test_legacy_public_path_errors_are_not_encoded_twice(
    configured: None,
) -> None:
    from fastapi import Depends

    codec = get_id_encryption_settings().resources["accounts/users"]
    app = FastAPI()
    setup_exception_handlers(
        app, id_encryptions=get_id_encryption_settings().entities
    )

    @app.get("/legacy/{id}")
    async def legacy(
        id: Annotated[int, Depends(decode_path_id(codec, "User"))],
    ) -> dict[str, int]:
        return {"id": id}

    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/legacy/9999")
    assert response.status_code == 404
    assert response.json()["error"]["identifier_value"] == "9999"


async def test_error_encoding_does_not_change_unconfigured_entities(
    configured: None,
) -> None:
    error = NotFoundException(
        entity="Role",
        identifier="id",
        identifier_value=42,
        message="Missing role 42",
        message_code=resources.NOT_FOUND_ERROR,
    )
    app = FastAPI()
    setup_exception_handlers(
        app, id_encryptions=get_id_encryption_settings().entities
    )

    @app.get("/missing")
    async def missing() -> None:
        raise error

    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/missing")
    assert response.json()["error"]["identifier_value"] == "42"
    assert response.json()["error"]["message"] == "Missing role 42"
