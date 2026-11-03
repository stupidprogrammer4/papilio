"""Native scoped injection and committed/rolled-back SQLite outcomes."""

import asyncio
import inspect
from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest
from anyio import move_on_after, sleep
from dishka import (
    AsyncContainer,
    FromDishka,
    Provider,
    Scope,
    make_async_container,
    provide,
)
from sqlalchemy import Column, Integer, MetaData, Table, insert, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from papilio.core.config import DatabaseConfig
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.transaction import TransactionRollbackOnly, transaction
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork
from papilio.infra.scopes import request_scoped
from papilio.providers.db import SQLiteProvider

records = Table(
    "scoped_records", MetaData(), Column("id", Integer, primary_key=True)
)


class RecordService:
    def __init__(self, unit: SQLiteUnitOfWork) -> None:
        self.unit = unit

    @transactional
    async def create(self, id: int) -> int:
        stmt = insert(records).values(id=id)
        await self.unit.execute(stmt)
        return id


class Services(Provider):
    service = provide(RecordService, scope=Scope.REQUEST)


@pytest.fixture
async def runtime(tmp_path):
    dsn = f"sqlite+aiosqlite:///{tmp_path}/scoped.db"
    config = DatabaseConfig(
        dsn=dsn,
        test_dsn=dsn,
        pool_size=4,
        max_overflow=0,
        pool_timeout=3,
        pool_recycle=1800,
    )
    container = make_async_container(SQLiteProvider(config), Services())
    database = await container.get(DBConnection[SQLiteUnitOfWork])
    async with database.engine.begin() as connection:
        await connection.run_sync(records.metadata.create_all)
    try:
        yield SimpleNamespace(
            container=container, database=database, config=config
        )
    finally:
        await container.close()


async def stored_ids(runtime):
    async with runtime.database.uow() as unit:
        stmt = select(records.c.id).order_by(records.c.id)
        result = await unit.execute(stmt)
        return list(result.scalars())


async def test_injects_service_and_closes_its_actual_session(runtime):
    units = []

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(id: int, *, service: FromDishka[RecordService]) -> int:
        units.append(service.unit)
        assert UnitOfWork.current() is service.unit
        result = await service.create(id)
        return result

    assert await operation(7) == 7
    assert await stored_ids(runtime) == [7]
    assert not units[0].is_open
    assert UnitOfWork.current() is None
    assert runtime.database.engine.pool.checkedout() == 0


async def test_scope_exit_never_commits_unmanaged_writes(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(*, unit: FromDishka[SQLiteUnitOfWork]) -> None:
        stmt = insert(records).values(id=1)
        await unit.execute(stmt)

    await operation()
    assert await stored_ids(runtime) == []


async def test_nested_calls_reuse_uow_without_closing_or_committing(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def inner(*, service: FromDishka[RecordService]) -> SQLiteUnitOfWork:
        await service.create(1)
        return service.unit

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def outer(*, unit: FromDishka[SQLiteUnitOfWork]) -> None:
        async with transaction():
            assert await inner() is unit
            assert unit.is_open
            assert await stored_ids(runtime) == []
            stmt = insert(records).values(id=2)
            await unit.execute(stmt)

    await outer()
    assert await stored_ids(runtime) == [1, 2]


async def test_caught_nested_transaction_failure_remains_rollback_only(
    runtime,
):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def inner(*, service: FromDishka[RecordService]) -> None:
        await service.create(1)

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def outer(*, service: FromDishka[RecordService]) -> None:
        async with transaction():
            await service.create(1)
            with pytest.raises(IntegrityError):
                await inner()

    with pytest.raises(TransactionRollbackOnly):
        await outer()
    assert await stored_ids(runtime) == []


async def test_borrows_explicit_request_without_closing_it(runtime):
    async with runtime.container(scope=Scope.REQUEST) as scope:
        expected = await scope.get(SQLiteUnitOfWork)

        @request_scoped(container_getter=lambda args, kwargs: scope)
        async def operation(*, unit: FromDishka[SQLiteUnitOfWork]) -> int:
            assert unit is expected
            stmt = select(11)
            result = await unit.execute(stmt)
            return result.scalar_one()

        assert await operation() == 11
        assert expected.is_open
    assert not expected.is_open


async def test_nested_root_call_reuses_a_borrowed_request(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def inner(*, unit: FromDishka[SQLiteUnitOfWork]):
        return unit

    async with runtime.container(scope=Scope.REQUEST) as scope:
        expected = await scope.get(SQLiteUnitOfWork)

        @request_scoped(container_getter=lambda args, kwargs: scope)
        async def outer(*, unit: FromDishka[SQLiteUnitOfWork]):
            assert await inner() is unit

        await outer()
        assert expected.is_open


async def test_transactional_can_be_composed_inside_the_scope_decorator(
    runtime,
):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    @transactional
    async def operation(id: int, *, unit: FromDishka[SQLiteUnitOfWork]) -> int:
        stmt = insert(records).values(id=id)
        await unit.execute(stmt)
        return id

    assert await operation(9) == 9
    assert await stored_ids(runtime) == [9]


async def test_concurrent_root_calls_have_distinct_live_units(runtime):
    barrier = asyncio.Barrier(2)
    units = []

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(id: int, *, unit: FromDishka[SQLiteUnitOfWork]) -> int:
        units.append(unit)
        stmt = select(id)
        result = await unit.execute(stmt)
        await asyncio.wait_for(barrier.wait(), 3)
        return result.scalar_one()

    assert await asyncio.gather(operation(3), operation(5)) == [3, 5]
    assert units[0] is not units[1]
    assert all(not unit.is_open for unit in units)
    assert runtime.database.engine.pool.checkedout() == 0


async def test_child_root_call_does_not_reuse_inherited_parent_scope(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def child(*, unit: FromDishka[SQLiteUnitOfWork]) -> SQLiteUnitOfWork:
        stmt = select(1)
        await unit.execute(stmt)
        return unit

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def parent(*, unit: FromDishka[SQLiteUnitOfWork]) -> None:
        other = await asyncio.create_task(child())
        assert other is not unit
        assert not other.is_open
        assert UnitOfWork.current() is unit
        assert unit.is_open

    await parent()


async def test_known_request_cannot_be_shared_with_child_task(runtime):
    @request_scoped(container_getter=lambda args, kwargs: args[0])
    async def child(container: AsyncContainer) -> None:
        pytest.fail("Inherited request must be rejected")

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def parent(*, scope: FromDishka[AsyncContainer]) -> None:
        with pytest.raises(RuntimeError, match="another or closed task"):
            await asyncio.create_task(child(scope))

    await parent()


async def test_inherited_closed_request_is_rejected(runtime):
    finished = asyncio.Event()
    child_task = None

    @request_scoped(container_getter=lambda args, kwargs: args[0])
    async def child(container: AsyncContainer) -> None:
        pytest.fail("Closed request must be rejected")

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def parent(*, scope: FromDishka[AsyncContainer]) -> None:
        nonlocal child_task

        async def delayed():
            await finished.wait()
            with pytest.raises(RuntimeError, match="another or closed task"):
                await child(scope)

        child_task = asyncio.create_task(delayed())

    await parent()
    finished.set()
    await child_task


@pytest.mark.parametrize("cancel", [False, True])
async def test_failure_rolls_back_and_releases_session(runtime, cancel):
    entered = asyncio.Event()
    units = []
    error = ValueError("body failed")

    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(*, unit: FromDishka[SQLiteUnitOfWork]) -> None:
        units.append(unit)
        async with transaction():
            stmt = insert(records).values(id=1)
            await unit.execute(stmt)
            entered.set()
            if cancel:
                await asyncio.Event().wait()
            raise error

    task = asyncio.create_task(operation())
    await asyncio.wait_for(entered.wait(), 3)
    if cancel:
        task.cancel()
    with pytest.raises(
        asyncio.CancelledError if cancel else ValueError
    ) as exc:
        await task
    if not cancel:
        assert exc.value is error
    assert not units[0].is_open
    assert await stored_ids(runtime) == []
    assert runtime.database.engine.pool.checkedout() == 0


async def test_returned_session_is_closed_and_cannot_execute(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(*, unit: FromDishka[SQLiteUnitOfWork]):
        return unit.session

    session = await operation()
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        await session.execute(select(1))


async def test_partial_dependency_failure_finalizes_native_providers(runtime):
    units = []
    error = LookupError("dependency failed")

    class BrokenProvider(Provider):
        @provide(scope=Scope.REQUEST)
        async def broken(self, unit: SQLiteUnitOfWork) -> str:
            units.append(unit)
            stmt = select(1)
            await unit.execute(stmt)
            raise error

    container = make_async_container(
        SQLiteProvider(runtime.config), BrokenProvider()
    )
    try:

        @request_scoped(container_getter=lambda args, kwargs: container)
        async def operation(*, value: FromDishka[str]) -> None:
            pytest.fail("Dependency resolution failed")

        with pytest.raises(LookupError) as exc:
            await operation()
        assert exc.value is error
        assert not units[0].is_open
    finally:
        await container.close()


async def test_timeout_finalizes_non_database_async_providers():
    finished = []

    class Resources(Provider):
        @provide(scope=Scope.REQUEST)
        async def resource(self) -> AsyncIterator[str]:
            try:
                yield "value"
            finally:
                await sleep(0.01)
                finished.append(True)

    container = make_async_container(Resources())
    try:

        @request_scoped(container_getter=lambda args, kwargs: container)
        async def operation(*, value: FromDishka[str]) -> None:
            await sleep(10)

        with move_on_after(0.01) as timeout:
            await operation()
        assert timeout.cancel_called
        assert finished == [True]
    finally:
        await container.close()


async def test_injected_argument_cannot_be_replaced_by_caller(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(*, service: FromDishka[RecordService]) -> None:
        pytest.fail("Caller must not replace injected dependencies")

    with pytest.raises(TypeError):
        await operation(service=object())


async def test_distinct_roots_never_reuse_each_others_units(runtime):
    other = make_async_container(SQLiteProvider(runtime.config))
    try:

        @request_scoped(container_getter=lambda args, kwargs: other)
        async def inner(*, unit: FromDishka[SQLiteUnitOfWork]):
            return unit

        @request_scoped(
            container_getter=lambda args, kwargs: runtime.container
        )
        async def outer(*, unit: FromDishka[SQLiteUnitOfWork]):
            other_unit = await inner()
            assert other_unit is not unit
            assert not other_unit.is_open
            assert UnitOfWork.current() is unit

        await outer()
    finally:
        await other.close()


async def test_no_injected_arguments_and_keyword_container_getter(runtime):
    @request_scoped(container_getter=lambda args, kwargs: kwargs["container"])
    async def operation(value: int, *, container: AsyncContainer) -> int:
        """Keep ordinary arguments and metadata."""
        assert UnitOfWork.current() is None
        return value

    assert await operation(4, container=runtime.container) == 4
    assert operation.__name__ == "operation"
    assert operation.__doc__ == "Keep ordinary arguments and metadata."


async def test_exposed_signature_hides_injected_arguments(runtime):
    @request_scoped(container_getter=lambda args, kwargs: runtime.container)
    async def operation(
        value: int,
        *,
        label: str = "default",
        unit: FromDishka[SQLiteUnitOfWork],
    ) -> tuple[int, str]:
        return value, label

    signature = inspect.signature(operation)
    assert list(signature.parameters) == ["value", "label"]
    assert signature.parameters["label"].default == "default"
    assert signature.return_annotation == tuple[int, str]
    assert await operation(3) == (3, "default")
    assert await operation(5, label="explicit") == (5, "explicit")


def test_rejects_sync_and_async_generator_functions():
    decorator = request_scoped(container_getter=lambda args, kwargs: None)

    async def stream() -> AsyncIterator[int]:
        yield 1

    for function in (lambda: None, stream):
        with pytest.raises(TypeError, match="requires an async function"):
            decorator(function)
