# Request-scoped function execution

`request_scoped` runs an async entrypoint with dependencies injected from a
native Dishka request scope. It replaces repeated scope opening and
`scope.get(...)` at execution boundaries. Business services and repositories
keep their constructor-injected dependencies.

## Bind an execution boundary

Given an application container with the normal database and service providers,
bind the container at the composition root:

```python
from collections.abc import Awaitable, Callable
from typing import cast

from dishka import FromDishka

from papilio.infra.scopes import request_scoped


async def calculate_price(
    variant_id: int, *, pricing: FromDishka[PricingService]
) -> Price:
    price = await pricing.calculate(variant_id)
    return price


calculate = cast(
    Callable[[int], Awaitable[Price]],
    request_scoped(container_getter=lambda args, kwargs: container)(
        calculate_price
    ),
)

price = await calculate(variant_id)
```

Here `PricingService` and `Price` are application-owned types. The container
getter has Dishka's public `ContainerGetter[AsyncContainer]` contract: it
receives the original positional tuple and keyword dictionary. It can instead
select a container supplied as an ordinary argument or held by an execution
adapter. No global application container is installed by Papilio.

Dishka removes `FromDishka` arguments from the runtime signature and preserves
ordinary arguments, defaults and return annotations. As with native Dishka
injection, Python's static type system cannot subtract arbitrary injected
parameters from a `ParamSpec`. When calling the bound entrypoint directly,
declare its public callable contract at the binding boundary, as above. The
underlying function and its injected dependencies remain explicitly typed.

Dependency resolution is lazy. A database UoW and session open only if a
resolved dependency requires them. Returning an ordinary cached result need
not resolve a database service. Put the decorator around the database phase,
not around a long workflow that also crawls sources or calls a payment provider.

## Ownership and nesting

- An APP or SESSION container opens a native REQUEST scope for an independent
  call. Only the outer owner finalizes that scope.
- A supplied REQUEST container is borrowed. Its caller remains responsible for
  its lifetime; the decorator does not close it.
- Nested decorated calls in the same task reuse an active request when their
  supplied container is that request or one of its ancestors. Different
  application containers retain independent scopes.
- Concurrent tasks supplied with the application container get distinct
  requests and UoWs, including child tasks of an active decorated operation.
  A child task cannot join its parent's application transaction. Native
  transaction ownership checks remain in force.
- Never pass a request container between tasks or use it after its owning
  context exits. The adapter rejects inherited requests it can identify from
  its own execution context. Externally opened request lifetimes and task
  ownership remain the caller's responsibility.

Native Dishka owns provider construction, caching and finalization. Cleanup is
shielded from AnyIO cancellation, matching Papilio's tool adapters; SQL UoW
cleanup also retains its native asyncio cancellation handling. Errors propagate
with their original meaning. The adapter does not retry or translate failures.

## Transactions stay explicit

The decorator manages scope lifetime. It does not commit or open an application
transaction. SQLAlchemy may still begin a SQL transaction lazily when SQL runs;
closing the session discards any uncommitted writes.

Normally the injected service owns its existing `@transactional` operation. An
entrypoint that itself coordinates a transaction can compose the decorators:

```python
from papilio.infra.db.tools.decorators import transactional


@request_scoped(container_getter=lambda args, kwargs: container)
@transactional
async def update_stock(
    product_id: int, *, service: FromDishka[StockService]
) -> StockResult:
    result = await service.update(product_id)
    return result
```

In this example the registered `StockService` depends on `PGUnitOfWork`, so
injection opens it before the inner `@transactional` wrapper runs. The order is
significant: put `@request_scoped` outside `@transactional`. Nested application
transactions retain their normal rollback-only behavior and commit only at the
outer transaction boundary. See [transactions](transactions.md).

## Result lifetime

The owned scope closes before the result reaches the caller. Return fully
materialized domain results. Do not return lazy ORM relationships, cursors,
session-dependent iterators or live services that need that scope later.
Streaming needs a separately owned streaming lifetime. Synchronous functions
and async generators are rejected when the decorator is applied.

HTTP routes, registered tools and native task integrations that already own
the appropriate request scope usually need no extra decorator. Keep their
existing native injection unless a separate, shorter operation is required.
