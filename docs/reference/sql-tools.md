# SQL tools and dialects

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.db.dialects.base`

### `DatabaseDialect`

```python
class DatabaseDialect:
    name = 'generic'
    def unique_values(self, error: IntegrityError) -> dict[str, Any] | None:
        ...
```

## `papilio.infra.db.dialects.mariadb`

### `MariaDBDialect`

```python
class MariaDBDialect(MySQLDialect):
    name = 'mariadb'
```

## `papilio.infra.db.dialects.mssql`

### `MSSQLDialect`

```python
class MSSQLDialect(DatabaseDialect):
    name = 'mssql'
    def unique_values(self, error):
        ...
```

## `papilio.infra.db.dialects.mysql`

### `MySQLDialect`

```python
class MySQLDialect(DatabaseDialect):
    name = 'mysql'
    def unique_values(self, error):
        ...
```

## `papilio.infra.db.dialects.oracle`

### `OracleDialect`

```python
class OracleDialect(DatabaseDialect):
    name = 'oracle'
    def unique_values(self, error):
        ...
```

### `OracleJSON`

```python
class OracleJSON(TypeDecorator[Any]):
    impl = Text
    cache_ok = True
    def __init__(self, *, none_as_null: bool=False):
        ...

    def process_bind_param(self, value, dialect):
        ...

    def process_result_value(self, value, dialect):
        ...

    def _cx_oracle_var(self, dialect, cursor, arraysize=1):
        ...
```

## `papilio.infra.db.dialects.postgresql`

### `PGDialect`

```python
class PGDialect(DatabaseDialect):
    name = 'postgresql'
    def unique_values(self, error):
        ...
```

### `reset_schema`

```python
async def reset_schema(connection):
    ...
```

### `truncate_tables`

```python
async def truncate_tables(session, tables):
    ...
```

### `JSONBField`

```python
def JSONBField(*, none_as_null: bool=False, **options: Unpack[FieldOptions]) -> Any:
    ...
```

### `ArrayField`

```python
def ArrayField(item_type: Any=BigInteger, *, dimensions: int | None=None, gin_index: str | None=None, **options: Unpack[FieldOptions]) -> Any:
    ...
```

## `papilio.infra.db.dialects.sqlite`

### `SQLiteDialect`

```python
class SQLiteDialect(DatabaseDialect):
    name = 'sqlite'
    def unique_values(self, error):
        ...
```

## `papilio.infra.db.tools.conflicts`

### `handle_conflicts`

```python
@overload
def handle_conflicts[**P, R](function: Callable[P, Awaitable[R]], *, entity: str | type | None=None, message: str | None=None, message_code: str | None=None) -> Callable[P, Coroutine[Any, Any, R]]:
    ...

@overload
def handle_conflicts[**P, R](function: None=None, *, entity: str | type | None=None, message: str | None=None, message_code: str | None=None) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]]:
    ...
```

Independent async decorator; selects the dialect from the current open UoW
at call entry. Recognized unique/primary-key violations become
`ConflictException`; other errors propagate unchanged. Optional entity and
message defaults, transaction composition and backend detail limits are
described in the [usage guide](../guide/transactions.md#optional-conflict-translation).

## `papilio.infra.db.tools.decorators`

### `transactional`

```python
def transactional[**P, R](function: Callable[P, Awaitable[R]]) -> Callable[P, Coroutine[Any, Any, R]]:
    ...
```

## `papilio.infra.db.tools.read`

### `fetch_page`

```python
async def fetch_page[T](uow: UnitOfWork, query: Select[tuple[T]], *, limit: int, offset: int=0) -> PagedType[T]:
    ...
```

### `stream`

```python
async def stream[T](uow: UnitOfWork, query: Select[tuple[T]], *, batch_size: int=100) -> AsyncIterator[T]:
    ...
```
