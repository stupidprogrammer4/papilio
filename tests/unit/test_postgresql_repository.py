"""Explicit PostgreSQL columns, composable builders and native execution."""

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import JSON, Integer, column, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import MultipleResultsFound
from sqlmodel import Field

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.repositories.backends.postgresql import (
    PGReader,
    PGRepository,
)
from papilio.infra.db.repositories.backends.sqlite import SQLiteRepository
from papilio.infra.db.schema.entity import BaseEntity
from papilio.infra.db.table import BaseTable
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import PGUnitOfWork, SQLiteUnitOfWork


class ToolEntity(BaseEntity):
    tenant: int = Field(primary_key=True)
    code: str = Field(primary_key=True)
    amount: int = 0
    payload: dict | None = Field(default=None, sa_type=JSON)


class PGToolTable(ToolEntity, BaseTable, table=True):
    pass


class ToolRepository(PGRepository[ToolEntity]):
    table = PGToolTable


columns = PGToolTable.__table__.c


def test_values_grid_uses_explicit_order_types_and_extra_columns():
    repo = ToolRepository(SimpleNamespace(session=None))
    grid = repo._values_grid(
        [{"amount": 3, "delta": 2, "unused": "not a column"}],
        columns=[column("delta", Integer), columns.amount],
        name="changes",
    )
    stmt = select(grid.c.delta, grid.c.amount)
    compiled = stmt.compile(dialect=postgresql.dialect())
    assert list(grid.c.keys()) == ["delta", "amount"]
    assert list(compiled.params.values()) == [2, 3]
    assert "unused" not in str(compiled)
    assert "changes" in str(compiled)


def test_builders_leave_returning_and_execution_options_to_caller():
    repo = ToolRepository(SimpleNamespace(session=None))
    rows = [{"tenant": 1, "code": "a", "amount": 3}]
    statements = [
        repo._upsert_stmt(
            rows[0],
            conflict_columns=[columns.tenant, columns.code],
            update_columns=[columns.amount],
        ),
        repo._bulk_update_stmt(
            rows,
            key_columns=[columns.tenant, columns.code],
            update_columns=[columns.amount],
        ),
    ]
    for stmt in statements:
        assert not stmt.get_execution_options()
        assert "RETURNING" not in str(
            stmt.compile(dialect=postgresql.dialect())
        )
        returned = stmt.returning(columns.amount)
        assert str(returned.compile(dialect=postgresql.dialect())).endswith(
            f"RETURNING {PGToolTable.__table__.name}.amount"
        )


async def test_single_upsert_does_not_dispatch_to_bulk(monkeypatch):
    returned = ToolEntity(tenant=1, code="a", amount=3)
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one=lambda: returned)
        )
    )
    repo = ToolRepository(SimpleNamespace(execute=session.execute))
    bulk = AsyncMock(side_effect=AssertionError("single routed through bulk"))
    monkeypatch.setattr(repo, "bulk_upsert", bulk)
    result = await repo.upsert(
        returned,
        conflict_columns=[columns.tenant, columns.code],
        update_columns=[columns.amount],
    )
    assert result is returned
    session.execute.assert_awaited_once()
    bulk.assert_not_awaited()


@pytest.fixture
async def postgres_tools():
    dsn = os.getenv("PAPILIO_TEST_POSTGRESQL")
    if not dsn:
        pytest.skip(
            "Set PAPILIO_TEST_POSTGRESQL for live PostgreSQL tool tests"
        )
    db = DBConnection(dsn, 2, 0, 5, 1800, uow_factory=PGUnitOfWork)
    created = False
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(PGToolTable.__table__.create)
            created = True
        yield db
    finally:
        if created:
            async with db.engine.begin() as conn:
                await conn.run_sync(PGToolTable.__table__.drop)
        await db.dispose()


async def test_composite_key_builders_and_selected_returning(postgres_tools):
    async with postgres_tools.uow() as unit, transaction():
        repo = ToolRepository(unit)
        await repo.bulk_create(
            [
                ToolEntity(tenant=1, code="a", amount=1),
                ToolEntity(tenant=2, code="a", amount=2),
            ]
        )
        stmt = (
            repo._bulk_update_stmt(
                [{"tenant": 1, "code": "a", "amount": 7}],
                key_columns=[columns.tenant, columns.code],
                update_columns=[columns.amount],
            )
            .where(columns.amount < 5)
            .returning(columns.amount)
            .execution_options(synchronize_session=False)
        )
        result = await unit.execute(stmt)
        assert result.all() == [(7,)]
        stmt = repo._upsert_stmt(
            {"tenant": 2, "code": "a", "amount": 100},
            conflict_columns=[columns.tenant, columns.code],
            update_columns=[],
            changes={columns.amount: columns.amount + 10},
        ).returning(columns.tenant, columns.amount)
        result = await unit.execute(stmt)
        assert result.all() == [(2, 12)]
        stmt = select(columns.tenant, columns.amount).order_by(columns.tenant)
        assert (await unit.execute(stmt)).all() == [(1, 7), (2, 12)]


async def test_ready_operations_work_without_id(postgres_tools):
    async with postgres_tools.uow() as unit, transaction():
        repo = ToolRepository(unit)
        await repo.create(ToolEntity(tenant=1, code="a", amount=1))
        await repo.upsert(
            ToolEntity(
                tenant=1, code="a", amount=2, payload={"ignored": True}
            ),
            conflict_columns=[columns.tenant, columns.code],
            update_columns=[columns.amount],
        )
        assert (await repo.get_one(columns.code == "a")).payload is None
        await repo.bulk_upsert(
            [
                ToolEntity(tenant=1, code="a", amount=4),
                ToolEntity(tenant=2, code="b", amount=5),
            ],
            insert_columns={
                "tenant": columns.tenant,
                "code": columns.code,
                "amount": columns.amount,
            },
            conflict_columns=[columns.tenant, columns.code],
            update_columns=[columns.amount],
        )
        assert await repo.count() == 2
        assert await repo.exists(columns.amount == 5)
        assert not await repo.exists(columns.amount == 100)
        assert await repo.get_one(columns.code == "missing") is None
        with pytest.raises(MultipleResultsFound):
            await repo.get_one()
        assert len(await repo.get_all(columns.tenant == 1)) == 1
        page = await repo.get_page(
            order_by=[columns.tenant, columns.code], limit=1, offset=1
        )
        assert page.total_items == 2 and page.items[0].tenant == 2
        assert [
            row.code
            async for row in repo.get_all_stream(
                1, where=[columns.tenant == 2]
            )
        ] == ["b"]
        updated = await repo.bulk_update(
            [{"tenant": 1, "code": "a", "amount": 6}],
            key_columns=[columns.tenant, columns.code],
            update_columns=[columns.amount],
        )
        assert [row.amount for row in updated] == [6]
        assert [
            row.amount
            for row in await repo.update(columns.tenant == 2, {"amount": 8})
        ] == [8]
        removed = await repo.remove(columns.tenant == 2)
        assert [(row.tenant, row.code, row.amount) for row in removed] == [
            (2, "b", 8)
        ]


async def test_reads_keep_pending_orm_changes_and_caller_can_refresh(
    postgres_tools,
):
    async with postgres_tools.uow() as unit, transaction():
        repo = ToolRepository(unit)
        query = PGReader(unit)
        row = await repo.create(ToolEntity(tenant=1, code="a", amount=1))
        statements = []
        event.listen(
            postgres_tools.engine.sync_engine,
            "before_cursor_execute",
            lambda conn, cursor, stmt, params, context, many: (
                statements.append(stmt)
            ),
        )
        row.amount = 99
        await repo.get_all()
        stmt = select(PGToolTable)
        result = await query.uow.execute(stmt)
        assert result.scalar_one() is row
        await repo.get_page(order_by=[columns.tenant], limit=10)
        assert [item.amount async for item in repo.get_all_stream()] == [99]
        assert row.amount == 99
        assert all(
            stmt.lstrip().upper().startswith("SELECT") for stmt in statements
        )
        stmt = select(PGToolTable).execution_options(populate_existing=True)
        result = await query.uow.execute(stmt)
        refreshed = result.scalar_one()
        assert refreshed is row and row.amount == 1


async def test_sqlite_upsert_accepts_composite_keys_without_id(tmp_path):
    class Repository(SQLiteRepository[ToolEntity]):
        table = PGToolTable

    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/composite.db",
        1,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(PGToolTable.__table__.create)
        async with db.uow() as unit, transaction():
            repo = Repository(unit)
            row = await repo.upsert(
                ToolEntity(tenant=1, code="a", amount=2),
                conflict_columns=[columns.tenant, columns.code],
                update_columns=[columns.amount],
            )
            assert row.amount == 2
            stmt = repo._bulk_upsert_stmt(
                [
                    {"tenant": 1, "code": "a", "amount": 4},
                    {"tenant": 2, "code": "a", "amount": 6},
                ],
                insert_columns={
                    "tenant": columns.tenant,
                    "code": columns.code,
                    "amount": columns.amount,
                },
                conflict_columns=[columns.tenant, columns.code],
                update_columns=[],
                changes={columns.amount: columns.amount + 10},
            )
            assert not stmt.get_execution_options()
            stmt = stmt.returning(columns.tenant, columns.amount)
            assert (await unit.execute(stmt)).all() == [(1, 12), (2, 6)]
    finally:
        await db.dispose()
