# API inputs, outputs and errors

The HTTP layer uses FastAPI and Pydantic. Papilio adds DTO conversion, query aliases, response envelopes, metadata and application error handlers. Endpoints can still return ordinary FastAPI responses.

## Validate input explicitly

```python
from pydantic import Field
from papilio.schemas.inputs import BaseDTO


class ProductCreate(BaseDTO):
    title: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=0, ge=0)
```

Use Pydantic validators for cross-field input rules. `data.to_row()` includes only explicitly set fields. Decide separately which fields can be omitted, which accept null, and which are writable. A database entity's `patch()` method does not validate external input.

## Query models

`BaseQuery` accepts explicit field aliases and Python field names. Declare query names with `Field(alias=...)`. Use `QueryPair` for a `<key>:<value>` string that should become a pair of nonnegative integers during validation:

```python
from typing import Annotated
from fastapi import APIRouter, Query
from pydantic import Field
from papilio.api.requests.queries import BaseQuery, QueryPair, pairs_folded


class ProductQuery(BaseQuery):
    ids: list[int] = Field(default_factory=list, alias="ids[]")
    picks: list[QueryPair] = Field(default_factory=list, alias="picks{}")
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=20, ge=1, le=100)

router = APIRouter()


@router.get("/filters")
async def filters(query: Annotated[ProductQuery, Query()]):
    return {"ids": query.ids, "picks": pairs_folded(query.picks)}
```

Example query string:

```text
/filters?ids%5B%5D=1&ids%5B%5D=2&picks%7B%7D=10:20&picks%7B%7D=10:21
```

After validation, `query.picks` is `[(10, 20), (10, 21)]`. `pairs_folded(query.picks)` groups those pairs into `{10: [20, 21]}` before JSON serialization, preserving value order and duplicates. An omitted list defaults to empty. No per-model pair validator is needed; OpenAPI describes the repeated input as strings.

Both parts must contain decimal digits. Zero, leading zeros and Persian decimal digits are accepted; signs, whitespace, missing or extra separators and numbers exceeding Python's integer-string conversion limit are rejected with HTTP 422 at the failing list item. Python construction also takes raw strings, for example `ProductQuery.model_validate({"picks": ["10:20"]})`; already-parsed tuples are not accepted as `QueryPair` input.

Migration: replace automatic list aliases with explicit `Field(alias=...)`, replace pair fields of type `list[str]` with `list[QueryPair]`, and remove `__mapped__` and validators calling `pairs_read`. Replace `query.folded("picks")` with `pairs_folded(query.picks)`. The grouping helper now accepts integer pairs, not raw strings. `BaseQuery` no longer rewrites fields or creates aliases automatically.

## Output schemas and envelopes

```python
from papilio.schemas.outputs import BaseOutput
from papilio.api.responses.envelope import APIResponse


class ProductOut(BaseOutput):
    id: int
    title: str


output = ProductOut(id=1, title="Notebook")
response = APIResponse[ProductOut, None].from_data(output)
```

Serialized result:

```json
{"success":true,"data":{"id":1,"title":"Notebook"}}
```

`BaseOutput.from_obj` and `from_objs` validate output from objects. At an endpoint, declare `response_model=APIResponse[ProductOut, None]` so FastAPI validates and documents the response. Absent optional envelope fields are omitted; `data` itself can remain null on error responses.

## Patch and deletion results

`PatchResult[T, P]` carries a result of type `T` and an applied patch of type
`P`. `DeleteResult[T]` carries a deletion result. Both are plain frozen, slotted
dataclasses, like `PagedType` and `BatchResultType`. They retain the supplied
Python objects without validation or conversion.

```python
from papilio.schemas.results import DeleteResult, PatchResult


patched = PatchResult[int, dict[str, str | None]](
    affected=1,
    value=42,
    patch={"title": None},
)

deleted = DeleteResult[None](affected=3, value=None)
```

`affected=None` represents an unknown count; zero represents a known zero.
The application supplies the result and applied patch, which can also use its
own before/after representation. An affected count alone does not prove that
stored values changed. Validation, public output schemas and serialization
belong to the application, just as they do for the other result containers.
At an HTTP boundary, explicitly map the result into your chosen output schema.

## Pagination metadata

Given a `PagedType` and the requested one-based page number:

```python
from papilio.api.responses.meta import BaseMeta, PagerMeta

response = APIResponse[ProductOut, BaseMeta](
    success=True,
    data=ProductOut.from_objs(page.items),
    meta=BaseMeta(
        pager=PagerMeta.from_total(
            page=page_number,
            per_page=20,
            total=page.total_items,
        ),
    ),
)
```

`PagerMeta` includes `total_items`, `total_pages`, `has_prev` and `has_next`. `SortMeta` describes available enum choices; `FilterMeta` describes filter options. Neither executes a database query.

## Application errors

Raise a typed error when an application decision fails:

```python
from papilio.errors.exceptions import NotFoundException

raise NotFoundException(
    message="Product not found",
    message_code="product.not_found",
    entity="product",
    identifier="id",
    identifier_value=42,
)
```

The default app handlers convert it to an error envelope with HTTP 404.

| Error | HTTP status |
| --- | --- |
| `ValidationException` | 400 |
| FastAPI request validation | 422 |
| `UnAuthorizedException` | 401 |
| `ForbiddenException` | 403 |
| `NotFoundException` | 404 |
| `ConflictException` | 409 |
| `TooManyRequestsException` | 429 |

`ValidationException` takes a field location and may contain child validation errors. `ConflictException` includes the conflicting fields. Unexpected errors produce the generic server-error envelope; write application-specific translations where their meaning is known.

## Services and reusable schemas

`Checks` and `IDChecks` provide protected validation/existence helpers for subclasses. They do not define your transaction or publish policy. `PagedType`, `BatchResultType`, `PatchResult` and `DeleteResult` are internal result containers; HTTP metadata and envelopes are separate. Utilities such as enum output schemas are listed in the [schema reference](../reference/schemas.md).

[Complete API reference](../reference/api.md)
