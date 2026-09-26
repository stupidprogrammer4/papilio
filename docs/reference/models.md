# SQL models and fields

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.schema.fields`

### `FieldOptions`

```python
class FieldOptions(TypedDict):
    default: Any
    default_factory: Callable[[], Any]
    nullable: bool
    index: bool
    unique: bool
    primary_key: bool
    db_column: str
    comment: str
    alias: str
    description: str
    server_default: Any
    onupdate: Any
    server_onupdate: Any
    sa_column_kwargs: Mapping[str, Any]
```

### `IDField`

```python
def IDField(*, autoincrement: bool=True, db_column: str | None=None) -> Any:
    ...
```

### `SmallIntField`

```python
def SmallIntField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `IntField`

```python
def IntField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `BigIntField`

```python
def BigIntField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `BoolField`

```python
def BoolField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `FloatField`

```python
def FloatField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `NumericField`

```python
def NumericField(precision: int | None=None, scale: int | None=None, **options: Unpack[FieldOptions]) -> Any:
    ...
```

### `CharField`

```python
def CharField(length: int, **options: Unpack[FieldOptions]) -> Any:
    ...
```

### `TextField`

```python
def TextField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `DateField`

```python
def DateField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `TimeField`

```python
def TimeField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

Stores a local clock time as SQLAlchemy `Time(timezone=False)` (`TIME WITHOUT
TIME ZONE` on PostgreSQL). Use a `datetime.time` annotation and the same
`FieldOptions` as other helpers:

```python
opens_at: time = TimeField()
closes_at: time | None = TimeField(nullable=True, default=None)
```

Import `time` from `datetime`. The field stores no date or timezone and performs
no timezone conversion. Validate timezone restrictions and schedule rules in
the input schema or application layer.

### `TimestampField`

```python
def TimestampField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `VersionField`

```python
def VersionField(**options: Unpack[FieldOptions]) -> Any:
    ...
```

### `JSONField`

```python
def JSONField(*, none_as_null: bool=False, **options: Unpack[FieldOptions]) -> Any:
    ...
```

### `EnumField`

```python
def EnumField(
    enum_cls: type[enum.Enum],
    *,
    native_enum: bool = True,
    values_callable: Callable[[type[enum.Enum]], list[str]] | None = None,
    length: int | None = None,
    **options: Unpack[FieldOptions],
) -> Any:
    ...
```

Defaults preserve SQLAlchemy's native enum and member-name storage. To keep an
existing text column and store member values while reading Python enum members:

```python
kind: ItemKind = EnumField(
    ItemKind,
    native_enum=False,
    values_callable=lambda members: [member.value for member in members],
    length=35,
)
```

This maps to `VARCHAR(35)` without creating a PostgreSQL enum or an enum check
constraint. With `length=None`, SQLAlchemy infers the length from stored strings.
Existing text values must match the selected enum values; unknown values raise
`LookupError` when read. The helper does not migrate existing columns or data.

### `ComputedField`

```python
def ComputedField(expression: str, type_: Any=Boolean, *, persisted: bool=True, **options: Unpack[FieldOptions]) -> Any:
    ...
```

### `ForeignKeyField`

```python
def ForeignKeyField(target: str, *, ondelete: str | None=None, **options: Unpack[FieldOptions]) -> Any:
    ...
```

## `papilio.infra.db.schema.entity`

### `BaseEntity`

```python
class BaseEntity(SQLModel):
    def to_dict(self, *, exclude_unset: bool=False) -> dict[str, Any]:
        ...

    def to_row(self, *, exclude_unset: bool=True) -> dict[str, Any]:
        ...

    def to_json(self, *, exclude_unset: bool=False) -> str:
        ...

    @classmethod
    def patch(cls, **fields: Any) -> Self:
        ...

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        ...

    @classmethod
    def from_dicts(cls, data: list[dict[str, Any]]) -> list[Self]:
        ...

    @classmethod
    def from_json(cls, raw: str | bytes) -> Self:
        ...

    @classmethod
    def carried(cls, raw: str | bytes) -> Any:
        ...

    @classmethod
    def from_obj(cls, obj: Any) -> Self:
        ...

    @classmethod
    def from_objs(cls, objs: Any) -> list[Self]:
        ...
```

### `IdentifiedEntity`

```python
class IdentifiedEntity(BaseEntity):
    id: int = IDField()
    def to_changes(self) -> dict[str, Any]:
        ...
```

### `TimestampEntity`

```python
class TimestampEntity(BaseEntity):
    created_at: datetime | None = TimestampField(default=None, server_default=func.current_timestamp())
    updated_at: datetime | None = TimestampField(default=None, server_default=func.current_timestamp(), onupdate=dates.utc_now)
```

### `VersionEntity`

```python
class VersionEntity(BaseEntity):
    version_num: int | None = VersionField(default=None, server_default=text('1'))
```

### `PersistenceEntity`

```python
class PersistenceEntity(IdentifiedEntity, TimestampEntity):
    ...
```

## `papilio.infra.db.table`

### `BaseTable`

```python
class BaseTable(AsyncAttrs, SQLModel):
    ...
```
