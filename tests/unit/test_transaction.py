"""SQL transaction boundaries on separate SQLite connections."""

import asyncio
from types import CoroutineType, SimpleNamespace
from typing import get_args, get_origin, get_type_hints
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import Column, Integer, MetaData, Table, insert, select
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.transaction import (
    TransactionRollbackOnly,
    current_transaction,
    transaction,
)
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork


def test_transactional_return_annotation_matches_native_async_methods():
    annotation = get_type_hints(transactional)["return"]
    assert get_origin(get_args(annotation)[1]) is CoroutineType


@pytest.fixture
async def runtime(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/data.db",
        4,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    metadata = MetaData()
    records = Table(
        "records", metadata, Column("id", Integer, primary_key=True)
    )
    async with db.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    try:
        yield SimpleNamespace(db=db, records=records)
    finally:
        await db.dispose()


async def write(runtime, id=1):
    unit = UnitOfWork.current()
    await unit.session.execute(insert(runtime.records).values(id=id))


async def rows(runtime):
    async with runtime.db.session_factory() as observer:
        return list(await observer.scalars(select(runtime.records.c.id)))


async def test_transaction_requires_an_open_unit():
    @transactional
    async def operation():
        pytest.fail("The body must not run without a UoW")

    with pytest.raises(RuntimeError, match="open UnitOfWork"):
        await operation()


async def test_session_scope_does_not_implicitly_commit(runtime):
    async with runtime.db.uow():
        await write(runtime)
    assert await rows(runtime) == []


@pytest.mark.parametrize("operation", ["commit", "rollback"])
async def test_manual_transaction_completion_is_rejected(runtime, operation):
    async with runtime.db.uow() as unit:
        with pytest.raises(RuntimeError, match="manually"):
            async with transaction():
                await write(runtime)
                await getattr(unit, operation)()


async def test_sequential_transactions_commit_independently(runtime):
    async with runtime.db.uow():
        for id in (1, 2):
            async with transaction():
                await write(runtime, id)
    assert await rows(runtime) == [1, 2]


async def test_parallel_operations_have_independent_transactions(runtime):
    async def operation(id):
        async with runtime.db.uow():
            async with transaction():
                await asyncio.sleep(0)
                await write(runtime, id)

    await asyncio.gather(operation(1), operation(2))
    assert sorted(await rows(runtime)) == [1, 2]


async def test_child_task_cannot_use_inherited_transaction(runtime):
    async with runtime.db.uow():
        async with transaction():

            async def child():
                async with transaction():
                    pytest.fail("Child must not enter inherited transaction")

            with pytest.raises(RuntimeError, match="another or closed task"):
                await asyncio.create_task(child())


@pytest.mark.parametrize("failure", ["body", "commit"])
async def test_failures_respect_actual_commit_boundary(
    runtime, monkeypatch, failure
):
    @transactional
    async def operation():
        await write(runtime)
        if failure == "body":
            raise ValueError("body")

    async with runtime.db.uow() as unit:
        rollback = AsyncMock(wraps=unit.rollback)
        monkeypatch.setattr(unit, "rollback", rollback)
        if failure == "commit":
            monkeypatch.setattr(
                unit, "commit", AsyncMock(side_effect=ValueError("commit"))
            )
        with pytest.raises(ValueError, match=failure):
            await operation()
        rollback.assert_awaited_once()
        with pytest.raises(RuntimeError, match="No active"):
            current_transaction()
    assert await rows(runtime) == []


@pytest.mark.parametrize("transactional_inner", [True, False])
async def test_only_nested_sql_failures_mark_rollback_only(
    runtime, transactional_inner
):
    async def fail():
        await write(runtime)
        raise ValueError("inner")

    inner = transactional(fail) if transactional_inner else fail

    @transactional
    async def outer():
        try:
            await inner()
        except ValueError:
            pass

    async with runtime.db.uow():
        if transactional_inner:
            with pytest.raises(TransactionRollbackOnly):
                await outer()
        else:
            await outer()
    assert await rows(runtime) == ([] if transactional_inner else [1])


@pytest.mark.parametrize("phase", ["body", "commit"])
async def test_cancellation_respects_commit_boundary(
    runtime, monkeypatch, phase
):
    reached = asyncio.Event()

    async def pause(*args):
        reached.set()
        await asyncio.Event().wait()

    @transactional
    async def write_record():
        await write(runtime)
        if phase == "body":
            await pause()

    async def operation():
        async with runtime.db.uow() as unit:
            if phase == "commit":
                monkeypatch.setattr(unit, "commit", pause)
            await write_record()

    task = asyncio.create_task(operation())
    await asyncio.wait_for(reached.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await rows(runtime) == []


def test_transactional_rejects_sync_functions():
    with pytest.raises(TypeError, match="async function"):
        transactional(lambda: None)


async def test_explicit_transaction_rejects_closed_unit(runtime):
    with pytest.raises(RuntimeError, match="not open"):
        async with transaction(runtime.db.uow()):
            pytest.fail("Closed units must not start transactions")


async def test_explicit_transaction_cannot_switch_parent_unit(runtime):
    async with runtime.db.uow() as first, runtime.db.uow() as second:
        async with transaction(first):
            with pytest.raises(RuntimeError, match="Cannot switch UoW"):
                async with transaction(second):
                    pytest.fail("A nested transaction cannot change databases")
            assert UnitOfWork.current() is first
        assert UnitOfWork.current() is second


async def test_explicit_transaction_restores_previous_unit_on_failure(runtime):
    async with runtime.db.uow() as first, runtime.db.uow() as second:
        with pytest.raises(ValueError, match="operation failed"):
            async with transaction(first):
                await write(runtime)
                raise ValueError("operation failed")
        assert UnitOfWork.current() is second
    assert await rows(runtime) == []


async def test_savepoint_failure_preserves_outer_transaction(runtime):
    async with runtime.db.uow() as unit:
        async with unit.transaction():
            await write(runtime, 1)
            with pytest.raises(IntegrityError):
                async with unit.savepoint():
                    await write(runtime, 1)
            assert unit.in_transaction
            await write(runtime, 2)
    assert await rows(runtime) == [1, 2]


async def test_released_savepoint_is_rolled_back_with_outer_scope(runtime):
    async with runtime.db.uow() as unit:
        with pytest.raises(ValueError):
            async with unit.transaction():
                async with unit.savepoint():
                    await write(runtime, 1)
                raise ValueError("abort outer transaction")
    assert await rows(runtime) == []


async def test_application_transaction_inside_savepoint_is_rejected(runtime):
    async with runtime.db.uow() as unit:
        async with unit.transaction():
            async with unit.savepoint():
                with pytest.raises(RuntimeError, match="inside a savepoint"):
                    async with unit.transaction():
                        pytest.fail(
                            "Application nesting cannot join a savepoint"
                        )
            await write(runtime, 1)
    assert await rows(runtime) == [1]


async def test_session_cannot_be_reused_after_unit_closes(runtime):
    async with runtime.db.uow() as unit:
        session = unit.session
    with pytest.raises(InvalidRequestError, match="permanently closed"):
        await session.execute(select(runtime.records))
