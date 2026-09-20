# Transactions and UnitOfWork

A connection owns the engine and pool. A UnitOfWork owns one session. A transaction context owns the commit/rollback boundary. Closing a UoW never commits implicitly.

## Open a unit and own a transaction

Given an existing connection, repository and valid input:

```python
from papilio.infra.db.transaction import transaction

async with connection.uow() as uow:
    repo = ProductRepository(uow)
    async with transaction(uow):
        product = await repo.create(data)
```

The inner context commits on success. On failure it rolls back and propagates the exception. The outer context closes the session. Repositories do not commit themselves. See the [SQLite example](../examples/index.md) for complete connection setup and disposal.

## Use a decorator in a service

```python
from papilio.infra.db.tools.decorators import transactional


class StockService:
    def __init__(self, repo: ProductRepository):
        self.repo = repo

    @transactional
    async def change(self, id: int, quantity: int):
        return await self.repo.update_by_id(id, {"quantity": quantity})
```

The decorator requires an open, active UoW, supplied by the request provider or a manual UoW context. Function inspection happens when the decorator is applied. Outside HTTP, enter `async with connection.uow()` before calling the service.

## Nested operations

Nested transactional services join the outer operation. They do not commit independently. If an inner operation fails, the transaction becomes rollback-only. Even when its caller catches the error, the outer boundary raises `TransactionRollbackOnly` instead of committing partial work.

A savepoint is the separate tool for an isolated SQL failure:

```python
from sqlalchemy.exc import IntegrityError

async with transaction(uow):
    try:
        async with uow.savepoint():
            await repo.create(optional_record)
    except IntegrityError:
        pass
    await repo.create(required_record)
```

Here both records are valid application inputs. Catch the SQL exception outside the savepoint scope. Entering a savepoint flushes pending ORM changes. Do not enter another `transaction()` or `@transactional` operation inside a savepoint.

## Available UoW tools

| Tool | Responsibility |
| --- | --- |
| `execute(stmt, params, execution_options=...)` | Return SQLAlchemy's buffered result |
| `stream(stmt, ...)` | Return an open cursor, which the caller closes |
| `flush()` | Send pending ORM changes without committing |
| `refresh(instance, attributes=...)` | Explicitly read an ORM object again |
| `commit()`, `rollback()` | Fully manual boundary management |
| `savepoint()` | Nested SQL transaction |
| `now()` | SELECT the database timestamp |
| `activate()`, `current()` | Select and access the contextual unit |

The option name is `execution_options`, not `execute_options`. It passes SQLAlchemy execution options through. Do not manually commit or roll back inside a managed transaction. `refresh()` and `now()` execute real reads.

## Optional conflict translation

Use the independent `handle_conflicts` decorator to translate database
unique/primary-key violations into `ConflictException` (HTTP 409). For a service
with an injected repository and an open request UoW:

```python
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.tools.checks import Checks


class ProductService(Checks):
    entity = "Product"

    def __init__(self, repo):
        self.repo = repo

    @handle_conflicts
    @transactional
    async def create(self, data):
        return await self.repo.create(data)
```

The decorator selects the dialect from the UoW active **when the call starts**.
A missing open UoW or unsupported backend fails before the body runs. Each
decorated call belongs to that selected unit/backend; decorate separate
operations for different databases and activate the correct unit before each
call. Opening a UoW only inside the decorated function is too late.

`handle_conflicts` never opens a transaction, commits, rolls back or retries.
Place it **outside** `@transactional`, as above, to translate errors after the
transaction has rolled back, including failures during its commit. Without a
managed transaction, the caller still owns rollback. Commit or cursor errors
that happen after the decorated call returns are outside its scope. Only async
functions are supported, not async generators.

All options are independent and optional:

```python
@handle_conflicts(
    entity="Product",  # A model class is also accepted; its __name__ is used.
    message="A product with these details already exists.",
    message_code="product.duplicate",
)
async def insert_product(repo, data):
    return await repo.create(data)
```

Entity naming uses an explicit string/class first, then `self.entity` for an
actual instance method on `Checks`, then generic record wording. An ordinary
function or staticmethod receiving a `Checks` object does not use it as the
entity. No model annotation or database schema inference is performed.

Without a custom message, known fields produce
`Product already exists with the same sku.`; without field details,
`Product already exists.`; without an entity,
`A record with these values already exists.` The default message code is
`conflict`. Only `None` selects a default, so an explicit empty string is kept.

The existing `unique_dict` contains field/value details only when the backend
can recover them reliably. PostgreSQL may supply textual values; absent,
localized or ambiguous details produce `{}`. The other adapters currently
recognize the violation without a field/value mapping. Values are not copied
into the generated message, and raw SQL or driver messages are not returned.
The original `IntegrityError` remains the exception cause.

Foreign-key, CHECK, NOT NULL and unrecognized failures keep their original
exception. Operations without this decorator also keep native errors. No
global error handling, repository or transaction configuration changes.

## Concurrency and multiple databases

Each concurrent task needs its own UoW. Do not share one session across branches of `asyncio.gather`. Repositories participating in one sequential operation can share a UoW.

Use explicitly typed connections and providers for different databases. You cannot switch the active unit inside an application transaction. This tool is not a distributed transaction: a SQL commit does not atomically include a Redis write or Elasticsearch request.

[Connection, UoW and transaction reference](../reference/transactions.md)
