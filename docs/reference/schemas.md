# Schemas, services and errors

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.errors.base`

### `APPException`

```python
class APPException[T: BaseErrorOut](Exception, ABC):
    def __init__(self, message: str, message_code: str, status_code: int, childs: list[APPException] | None=None) -> None:
        ...

    @abstractmethod
    def as_schema(self) -> T:
        ...
```

## `papilio.errors.exceptions`

### `ValidationException`

```python
class ValidationException(APPException[ValidationErrorOut]):
    def __init__(self, message: str, message_code: str, loc: list[Any], input: Any | None=None, ctx: dict[str, Any] | None=None, childs: Sequence[ValidationException] | None=None) -> None:
        ...

    def as_schema(self) -> ValidationErrorOut:
        ...

    @classmethod
    def get_invalid_input(cls, childs: Sequence[ValidationException]) -> ValidationException:
        ...
```

### `UnAuthorizedException`

```python
class UnAuthorizedException(APPException[UnAuthorizedErrorOut]):
    def __init__(self, message: str, message_code: str) -> None:
        ...

    def as_schema(self) -> UnAuthorizedErrorOut:
        ...
```

### `ForbiddenException`

```python
class ForbiddenException(APPException[ForbiddenErrorOut]):
    def __init__(self, message: str, message_code: str, user_id: int | None=None) -> None:
        ...

    def as_schema(self) -> ForbiddenErrorOut:
        ...
```

### `NotFoundException`

```python
class NotFoundException(APPException[NotFoundErrorOut]):
    def __init__(self, message: str, message_code: str, entity: str, identifier: str, identifier_value: Any) -> None:
        ...

    def as_schema(self) -> NotFoundErrorOut:
        ...
```

### `ConflictException`

```python
class ConflictException(APPException[ConflictErrorOut]):
    def __init__(self, message: str, message_code: str, unique_dict: dict[str, Any]) -> None:
        ...

    def as_schema(self) -> ConflictErrorOut:
        ...
```

### `TooManyRequestsException`

```python
class TooManyRequestsException(APPException[TooManyRequestsErrorOut]):
    def __init__(self, message: str, message_code: str, limit: int, remaining: int, retry_after: int) -> None:
        ...

    def as_schema(self) -> TooManyRequestsErrorOut:
        ...
```

## `papilio.errors.outputs`

### `BaseErrorOut`

```python
class BaseErrorOut(BaseModel):
    message_code: str
    message: str
```

### `ValidationErrorOut`

```python
class ValidationErrorOut(BaseErrorOut):
    loc: Sequence[Any]
    input: Any | None = None
    ctx: dict[str, Any] | None = None
    errors: Sequence[ValidationErrorOut] | None = None
```

### `NotFoundErrorOut`

```python
class NotFoundErrorOut(BaseErrorOut):
    entity: str
    identifier: str
    identifier_value: str
```

### `ForbiddenErrorOut`

```python
class ForbiddenErrorOut(BaseErrorOut):
    user_id: int | None = None
```

### `UnAuthorizedErrorOut`

```python
class UnAuthorizedErrorOut(BaseErrorOut):
    ...
```

### `ConflictErrorOut`

```python
class ConflictErrorOut(BaseErrorOut):
    unique_dict: dict[str, Any]
```

### `TooManyRequestsErrorOut`

```python
class TooManyRequestsErrorOut(BaseErrorOut):
    limit: int
    remaining: int
    retry_after: int
```

```python
errors_types = [BaseErrorOut, ValidationErrorOut, NotFoundErrorOut, ForbiddenErrorOut, UnAuthorizedErrorOut, ConflictErrorOut, TooManyRequestsErrorOut]
```

## `papilio.schemas.inputs`

### `BaseDTO`

```python
class BaseDTO(BaseModel):
    def to_row(self, *, exclude_unset: bool=True) -> dict[str, Any]:
        ...
```

### `SupportsToRow`

```python
class SupportsToRow(Protocol):
    def to_row(self, *, exclude_unset: bool=...) -> dict[str, Any]:
        ...
```

## `papilio.schemas.outputs`

### `BaseOutput`

```python
class BaseOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    @classmethod
    def from_obj(cls, model: Any) -> Self:
        ...

    @classmethod
    def from_objs(cls, models: Sequence[Any]) -> list[Self]:
        ...

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Self:
        ...

    @classmethod
    def from_dicts(cls, data: Sequence[Any]) -> list[Self]:
        ...
```

### `BaseIDOutput`

```python
class BaseIDOutput(BaseOutput):
    id: int
    @field_serializer('id')
    def _encode_id(self, id: int) -> int:
        ...
```

### `EnumOut`

```python
class EnumOut(BaseOutput):
    value: str
    label: str
    @classmethod
    def of(cls, enum: type[FaStrEnum]) -> list['EnumOut']:
        ...
```

### `EnumGroupOut`

```python
class EnumGroupOut(BaseOutput):
    name: str
    members: list[EnumOut]
    @classmethod
    def of(cls, enums: Sequence[type[FaStrEnum]]) -> list['EnumGroupOut']:
        ...
```

## `papilio.schemas.results`

### `PatchResult`

```python
@dataclass(frozen=True, slots=True)
class PatchResult[T, P]:
    affected: int | None
    value: T
    patch: P
```

The application supplies the result and the patch it applied. `affected=None`
means unknown; zero is a known zero. The count does not establish that old and
new values differ. This dataclass retains supplied objects without validation,
coercion or serialization.

### `DeleteResult`

```python
@dataclass(frozen=True, slots=True)
class DeleteResult[T]:
    affected: int | None
    value: T
```

Both fields are required, with the same count semantics. `T` can be any
application-selected type. Like the other result containers, this dataclass
does not validate, convert or serialize its payload. See the
[operation result examples](../guide/api.md#patch-and-deletion-results).

### `BatchResultType`

```python
class BatchResultType[T, E]:
    items: Sequence[T]
    errors: Sequence[E]
    item_ids: set[int] = field(default_factory=set)
```

```python
TItem = TypeVar('TItem', covariant=True)
```

### `PagedType`

```python
class PagedType(Generic[TItem]):
    items: Sequence[TItem]
    total_items: int
```

## `papilio.tools.checks`

### `HasID`

```python
class HasID(Protocol):

    @property
    def id(self) -> int:
        ...
```

### `Checks`

```python
class Checks[TModel]:
    entity: str

    def _check_not_empty_dict(self, d: dict):
        ...

    def _check_not_empty_list(self, ls: list):
        ...

    def _check_for_existence(self, identifier: str, identifier_value: Any, obj: TModel | None) -> TModel:
        ...

    def _check_batch_data(self, found_ids: Sequence[int], input_ids: Sequence[int], prefix_loc: list[str]) -> Sequence[ValidationException]:
        ...

    def _func_check_batch_data(self, input_values: Sequence[Any], found_objs: Sequence[TModel], key: Callable[[TModel], Any], identifier: str, loc: list[str] | None=None) -> BatchResultType[TModel, ValidationException]:
        ...
```

### `IDChecks`

```python
class IDChecks[TIDModel: HasID](Checks[TIDModel]):

    def _check_for_id_existence(self, id: int, obj: TIDModel | None):
        ...

    def _check_batch_data(self, input_ids: Sequence[int], found_objs: Sequence[TIDModel], loc: list[str] | None=None) -> BatchResultType[TIDModel, ValidationException]:
        ...

    def _func_check_batch_data(self, input_values: Sequence[Any], found_objs: Sequence[TIDModel], key: Callable[[TIDModel], Any], identifier: str, loc: list[str] | None=None) -> BatchResultType[TIDModel, ValidationException]:
        ...
```
