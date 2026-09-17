# API adapters

Signatures from this checkout. Providers and reusable tools are explicitly selected; these declarations are reference snippets.

## `papilio.api.dependencies.auth`

### `Scoped`

```python
class Scoped(Protocol):

    @property
    def scopes(self) -> frozenset[str]:
        ...
```

### `bearer`

```python
def bearer[T](authenticate: Callable[[str], Awaitable[T]]) -> Callable[..., Awaitable[T]]:
    ...
```

### `require_access`

```python
def require_access[T: Scoped](principal: Callable[..., Awaitable[T]], scope: str) -> Callable[..., Awaitable[T]]:
    ...
```

## `papilio.api.dependencies.ids`

### `decode_path_id`

```python
def decode_path_id(encryption: IDEncryption, entity: str, param: str='id') -> Callable[..., int]:
    ...
```

## `papilio.api.dependencies.rate_limit`

### `by_ip`

```python
async def by_ip(request: Request) -> str:
    ...
```

### `by_body_field`

```python
def by_body_field(field: str) -> KeyPart:
    ...
```

### `rate_limit`

```python
def rate_limit(name: str, parts: Sequence[KeyPart]=(by_ip,), *, closed_when_down: bool=False) -> Depends:
    ...
```

## `papilio.api.middlewares.logging`

### `LoggingMiddleware`

```python
class LoggingMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: ASGIApp, header_name: str='X-Request-ID') -> None:
        ...

    async def dispatch(self, request: Request, call_next) -> Response:
        ...
```

## `papilio.api.middlewares.rate_limit`

### `RateLimitMiddleware`

```python
class RateLimitMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        ...
```

## `papilio.api.requests.queries`

### `QueryPair`

```python
QueryPair = Annotated[
    tuple[int, int],
    BeforeValidator(_parse_pair, json_schema_input_type=str),
]
```

A string-input type for `<key>:<value>` query parameters. Validates and converts decimal digits to a pair of nonnegative integers. Rejects malformed or unconvertible input during model validation; a list field reports the failing item index. OpenAPI exposes string input. Python model construction also requires raw strings, not tuples.

### `pairs_folded`

```python
def pairs_folded(value: Sequence[tuple[int, int]]) -> dict[int, list[int]]:
    ...
```

Groups already-validated pairs by key, preserving value order and duplicates. Does not parse strings.

### `BaseQuery`

```python
class BaseQuery(BaseDTO):
    model_config = ConfigDict(populate_by_name=True)
```

Thin input model with explicit aliases and field-name population. Declare aliases with `Field(alias=...)`; no automatic naming or pair-field registration. See the [query guide](../guide/api.md#query-models) for usage and migration.

## `papilio.api.responses.envelope`

### `APIResponse`

```python
class APIResponse[TOut: BaseModel | None, TMeta: BaseModel | None](BaseModel):
    success: bool
    message_code: Optional[str] = None
    data: Optional[Union[TOut, Sequence[TOut]]] = None
    meta: Optional[TMeta] = None
    error: Optional[ErrorType] = None
    errors: Optional[Sequence[ErrorType]] = None
    _optional_envelope: ClassVar[tuple[str, ...]] = ('message_code', 'meta', 'error', 'errors')

    @model_serializer(mode='wrap')
    def _omit_empty_envelope(self, handler: SerializerFunctionWrapHandler) -> Any:
        ...

    @classmethod
    def from_data(cls, data: Union[TOut, Sequence[TOut]], message_code: Optional[str]=None, errors: Optional[Sequence[APPException]]=None):
        ...

    @classmethod
    def from_external_error(cls, error: APPException):
        ...

    @classmethod
    def from_pydantic_error(cls, error: PydanticError):
        ...

    @staticmethod
    def _readable_context(context: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        ...

    @classmethod
    def get_server_error(cls):
        ...
```

## `papilio.api.responses.handlers`

### `external_error_handler`

```python
async def external_error_handler(request: Request, exc: APPException) -> JSONResponse:
    ...
```

### `pydantic_error_handler`

```python
async def pydantic_error_handler(request: Request, exc: PydanticError) -> JSONResponse:
    ...
```

### `http_error_handler`

```python
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    ...
```

### `unexcepted_error_handler`

```python
def unexcepted_error_handler(request: Request, exc: Exception) -> JSONResponse:
    ...
```

### `setup_exception_handlers`

```python
def setup_exception_handlers(app: FastAPI) -> None:
    ...
```

## `papilio.api.responses.csrf`

### `csrf_error_handler`

```python
async def csrf_error_handler(request: Request, exc: CsrfProtectError) -> JSONResponse:
    ...
```

## `papilio.api.responses.meta`

### `PagerMeta`

```python
class PagerMeta(BaseModel):
    total_items: int
    total_pages: int
    has_prev: bool
    has_next: bool

    @classmethod
    def from_total(cls, page: int, per_page: int, total: int) -> Self:
        ...
```

### `SortMeta`

```python
class SortMeta(BaseModel):
    options: list[EnumOut]
    orders: list[EnumOut]

    @classmethod
    def of(cls, options: type[FaStrEnum]) -> 'SortMeta':
        ...
```

### `FilterMeta`

```python
class FilterMeta[TOut: BaseModel](BaseModel):
    id: int | None = None
    type: FilterType
    title: str | None = None
    options: list[TOut]
```

### `BaseMeta`

```python
class BaseMeta(BaseModel):
    pager: PagerMeta | None = None
    filters: dict[str, FilterMeta] | None = None
    sorts: SortMeta | None = None
```
