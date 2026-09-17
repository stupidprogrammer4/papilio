import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import TypeAdapter, ValidationError

from papilio.api.responses.handlers import setup_exception_handlers
from papilio.types.aliases import SlugType


@pytest.fixture
def slug_app() -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/slug")
    async def read_slug(slug: SlugType):
        return {"slug": slug}

    return app


@pytest.mark.parametrize(
    "value", ["ab", "a" * 55, "hello-world", "a0-9z", "--", "-ab", "ab--"]
)
async def test_valid_slugs_are_preserved(slug_app, value) -> None:
    assert TypeAdapter(SlugType).validate_python(value) == value
    async with AsyncClient(
        transport=ASGITransport(app=slug_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/slug", params={"slug": value})
    assert response.status_code == 200
    assert response.json() == {"slug": value}


@pytest.mark.parametrize(
    "value",
    [
        "",
        "a",
        "a" * 56,
        "hello!",
        "ab/../../escape",
        "ab\n",
        "ab\r\n",
        "ab cd",
        " ab",
        "ab ",
        "ab\t",
        "abC",
        "AB",
        "ab_",
        "abسلام",
    ],
)
async def test_invalid_slugs_fail_validation_and_return_422(
    slug_app, value
) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(SlugType).validate_python(value)

    async with AsyncClient(
        transport=ASGITransport(app=slug_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/slug", params={"slug": value})
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["loc"] == ["slug"]
    assert error["input"] == value


def test_slug_limits_are_exposed_in_openapi(slug_app) -> None:
    parameter = slug_app.openapi()["paths"]["/slug"]["get"]["parameters"][0]
    assert parameter["name"] == "slug"
    assert parameter["in"] == "query"
    schema = parameter["schema"]
    assert schema["type"] == "string"
    assert schema["minLength"] == 2
    assert schema["maxLength"] == 55
    assert schema["pattern"] == r"^[a-z0-9-]+$"
