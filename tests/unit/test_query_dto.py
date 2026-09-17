import sys
from typing import Annotated

import pytest
from fastapi import FastAPI, Query
from httpx import ASGITransport, AsyncClient
from pydantic import Field, TypeAdapter, ValidationError

from papilio.api.requests.queries import BaseQuery, QueryPair, pairs_folded
from papilio.api.responses.handlers import setup_exception_handlers


class SearchQuery(BaseQuery):
    statuses: list[str] = Field(default_factory=list, alias="statuses[]")
    attributes: list[QueryPair] = Field(
        default_factory=list, alias="attributes{}"
    )


@pytest.fixture
def query_app() -> FastAPI:
    app = FastAPI()
    setup_exception_handlers(app)

    @app.get("/search")
    async def search(query: Annotated[SearchQuery, Query()]):
        return {
            "statuses": query.statuses,
            "attributes": pairs_folded(query.attributes),
        }

    return app


@pytest.mark.parametrize(
    ("statuses", "attributes"),
    [("statuses[]", "attributes{}"), ("statuses", "attributes")],
)
def test_query_accepts_aliases_and_field_names(statuses, attributes) -> None:
    query = SearchQuery.model_validate(
        {
            statuses: ["active"],
            attributes: ["3:7", "4:2", "3:9", "3:7"],
        }
    )

    assert query.statuses == ["active"]
    assert query.attributes == [(3, 7), (4, 2), (3, 9), (3, 7)]
    assert pairs_folded(query.attributes) == {3: [7, 9, 7], 4: [2]}


def test_query_keeps_explicit_and_unaliased_fields() -> None:
    class CustomQuery(BaseQuery):
        tags: list[str] = Field(default_factory=list)
        selected: list[QueryPair] | None = Field(default=None, alias="choice")

    query = CustomQuery.model_validate({"tags": ["a"], "choice": ["1:2"]})
    assert query.tags == ["a"]
    assert query.selected == [(1, 2)]
    assert CustomQuery.model_fields["tags"].alias is None
    assert CustomQuery.model_fields["selected"].alias == "choice"
    assert CustomQuery.model_validate({"choice": None}).selected is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0:0", (0, 0)), ("01:002", (1, 2)), ("۱۲:۳", (12, 3))],
)
async def test_query_preserves_valid_digits(query_app, raw, expected) -> None:
    query = SearchQuery.model_validate({"attributes": [raw]})
    assert query.attributes == [expected]
    async with AsyncClient(
        transport=ASGITransport(app=query_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/search", params={"attributes{}": raw})
    assert response.status_code == 200
    assert response.json()["attributes"] == {str(expected[0]): [expected[1]]}


async def test_repeated_query_values_preserve_order_and_duplicates(
    query_app,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=query_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/search",
            params=[
                ("statuses[]", "active"),
                ("statuses[]", "pending"),
                ("attributes{}", "3:7"),
                ("attributes{}", "4:2"),
                ("attributes{}", "3:9"),
                ("attributes{}", "3:7"),
            ],
        )
    assert response.status_code == 200
    assert response.json() == {
        "statuses": ["active", "pending"],
        "attributes": {"3": [7, 9, 7], "4": [2]},
    }


async def test_missing_query_lists_are_empty(query_app) -> None:
    query = SearchQuery.model_validate({})
    assert query.attributes == []
    assert pairs_folded(query.attributes) == {}
    async with AsyncClient(
        transport=ASGITransport(app=query_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get("/search")
    assert response.status_code == 200
    assert response.json() == {"statuses": [], "attributes": {}}


async def _assert_invalid_pair(query_app: FastAPI, raw: str) -> None:
    with pytest.raises(ValidationError) as exc:
        SearchQuery.model_validate({"attributes{}": ["1:2", raw]})
    assert exc.value.errors()[0]["loc"] == ("attributes{}", 1)

    async with AsyncClient(
        transport=ASGITransport(app=query_app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/search", params=[("attributes{}", "1:2"), ("attributes{}", raw)]
        )
    assert response.status_code == 422
    error = response.json()["errors"][0]
    assert error["loc"] == ["attributes{}", 1]
    assert error["input"] == raw
    assert error["message_code"] == "value_error"


@pytest.mark.parametrize(
    "raw",
    [
        "²:1",
        "1:²",
        "",
        "bad",
        "3",
        ":",
        ":1",
        "1:",
        "1:2:3",
        "-1:2",
        "1:-2",
        "+1:2",
        "1:+2",
        " 1:2",
        "1:2 ",
        "1.0:2",
    ],
)
async def test_invalid_pairs_fail_during_validation(query_app, raw) -> None:
    await _assert_invalid_pair(query_app, raw)


@pytest.mark.parametrize("part", ["key", "value"])
async def test_overlong_integer_fails_during_validation(
    query_app, part
) -> None:
    limit = sys.get_int_max_str_digits()
    if not limit:
        pytest.skip("interpreter integer-string conversion limit is disabled")
    digits = "9" * (limit + 1)
    raw = f"{digits}:1" if part == "key" else f"1:{digits}"
    await _assert_invalid_pair(query_app, raw)


@pytest.mark.parametrize("value", [None, 12, (1, 2), [1, 2]])
def test_pair_input_requires_a_string(value) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(QueryPair).validate_python(value)


def test_openapi_describes_repeated_string_input(query_app) -> None:
    operation = query_app.openapi()["paths"]["/search"]["get"]
    assert "requestBody" not in operation
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert set(parameters) == {"statuses[]", "attributes{}"}
    for parameter in parameters.values():
        assert parameter["in"] == "query"
        assert parameter["required"] is False
        assert parameter["schema"]["type"] == "array"
        assert parameter["schema"]["items"]["type"] == "string"
