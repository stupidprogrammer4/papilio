"""Explicit repositories, native SQL, and behavioral contracts."""

import ast
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import (
    JSON,
    BigInteger,
    event,
    func,
    null,
    select,
    text,
    update,
)
from sqlalchemy.dialects import mssql, mysql, oracle, postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlmodel import Field

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.dialects.oracle import OracleJSON
from papilio.infra.db.repositories.backends import (
    mariadb as maria_repos,
)
from papilio.infra.db.repositories.backends import mssql as ms_repos
from papilio.infra.db.repositories.backends import mysql as my_repos
from papilio.infra.db.repositories.backends import oracle as ora_repos
from papilio.infra.db.repositories.backends import (
    postgresql as pg_repos,
)
from papilio.infra.db.repositories.backends import sqlite as lite_repos
from papilio.infra.db.schema.entity import (
    BaseEntity,
    PersistenceEntity,
    TimestampEntity,
    VersionEntity,
)
from papilio.infra.db.table import BaseTable
from papilio.infra.db.transaction import transaction
from papilio.infra.db.uow import (
    MariaDBUnitOfWork,
    MSSQLUnitOfWork,
    MySQLUnitOfWork,
    OracleUnitOfWork,
    PGUnitOfWork,
    SQLiteUnitOfWork,
)


class ProbeEntity(PersistenceEntity, VersionEntity):
    code: str = Field(max_length=64, unique=True)
    quantity: int = Field(default=0)
    note: str | None = Field(
        default=None,
        max_length=32,
        sa_column_kwargs={"server_default": "fallback"},
    )
    attributes: dict | None = Field(
        default=None,
        sa_type=cast(Any, JSON().with_variant(OracleJSON(), "oracle")),
    )
    # This test model chooses version advancement explicitly.
    version_num: int | None = Field(
        default=None,
        sa_type=BigInteger,
        nullable=False,
        sa_column_kwargs={
            "server_default": text("1"),
            "onupdate": text("version_num + 1"),
        },
    )


class RepositoryProbeTable(ProbeEntity, BaseTable, table=True):
    pass


class CodeEntity(BaseEntity):
    code: str = Field(primary_key=True)


class CodeTable(CodeEntity, BaseTable, table=True):
    pass


class DatedEntity(TimestampEntity):
    code: str = Field(primary_key=True)


class DatedTable(DatedEntity, BaseTable, table=True):
    pass


class SQLiteProbe(lite_repos.SQLitePersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class MySQLProbe(my_repos.MySQLPersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class PGProbe(pg_repos.PGPersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class MariaDBProbe(maria_repos.MariaDBPersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class OracleProbe(ora_repos.OraclePersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class MSSQLProbe(ms_repos.MSSQLPersistenceRepository[ProbeEntity]):
    table = RepositoryProbeTable


class CodeRepository(lite_repos.SQLiteRepository[CodeEntity]):
    table = CodeTable


class DatedRepository(lite_repos.SQLiteTimestampRepository[DatedEntity]):
    table = DatedTable


FAMILIES = [
    (pg_repos, "PG", True),
    (my_repos, "MySQL", True),
    (maria_repos, "MariaDB", True),
    (lite_repos, "SQLite", True),
    (ora_repos, "Oracle", False),
    (ms_repos, "MSSQL", False),
]


@pytest.mark.parametrize("module,prefix,upsert", FAMILIES)
def test_four_shapes_and_only_supported_capabilities(module, prefix, upsert):
    for shape in ("", "Identified", "Timestamp", "Persistence"):
        cls = vars(module)[f"{prefix}{shape}Repository"]
        supports_upsert = upsert
        assert hasattr(cls, "upsert") is supports_upsert
        assert hasattr(cls, "bulk_upsert") is supports_upsert
        assert hasattr(cls, "_upsert_stmt") is supports_upsert
        assert hasattr(cls, "_bulk_upsert_stmt") is supports_upsert
        assert hasattr(cls, "get_by_id") is (
            shape in ("Identified", "Persistence")
        )
        assert hasattr(cls, "get_stream_range") is (
            shape in ("Timestamp", "Persistence")
        )
    tree = ast.parse(Path(module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in (
                    "getattr",
                    "hasattr",
                    "get_args",
                    "get_origin",
                    "inspect",
                )
            if (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
            ):
                assert isinstance(node.args[0], ast.Name)
                assert node.args[0].id == "stmt"


@pytest.mark.parametrize(
    "dialect",
    [
        postgresql.dialect(),
        mysql.dialect(),
        sqlite.dialect(),
        mssql.dialect(),
        oracle.dialect(),
    ],
)
def test_schema_compilation(dialect):
    ddl = str(
        CreateTable(RepositoryProbeTable.__table__).compile(dialect=dialect)
    )
    assert "CURRENT_TIMESTAMP" in ddl


@pytest.fixture(
    params=[
        "sqlite",
        "mysql-orm",
        "postgresql",
        "mysql",
        "mariadb",
        "oracle",
        "mssql",
    ]
)
async def runtime(request, tmp_path):
    backend = request.param
    url = (
        f"sqlite+aiosqlite:///{tmp_path}/data.db"
        if backend in ("sqlite", "mysql-orm")
        else os.environ.get(f"PAPILIO_TEST_{backend.upper()}")
    )
    if not url:
        pytest.skip(
            f"Set PAPILIO_TEST_{backend.upper()} for live backend tests"
        )
    uow_factories = {
        "sqlite": SQLiteUnitOfWork,
        "mysql-orm": MySQLUnitOfWork,
        "postgresql": PGUnitOfWork,
        "mysql": MySQLUnitOfWork,
        "mariadb": MariaDBUnitOfWork,
        "oracle": OracleUnitOfWork,
        "mssql": MSSQLUnitOfWork,
    }
    db = DBConnection(url, 2, 0, 5, 1800, uow_factory=uow_factories[backend])
    repositories = {
        "sqlite": SQLiteProbe,
        "mysql-orm": MySQLProbe,
        "postgresql": PGProbe,
        "mysql": MySQLProbe,
        "mariadb": MariaDBProbe,
        "oracle": OracleProbe,
        "mssql": MSSQLProbe,
    }
    repo_type = repositories[backend]
    table = RepositoryProbeTable.__table__
    created = False
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(table.create)
            created = True
        yield SimpleNamespace(db=db, repo_type=repo_type, backend=backend)
    finally:
        if created:
            async with db.engine.begin() as conn:
                await conn.run_sync(table.drop)
        await db.dispose()


async def update_probe_batch(repo, data, *, columns):
    if isinstance(repo, PGProbe):
        return await repo.bulk_update(
            [item.to_row() for item in data],
            key_columns=[RepositoryProbeTable.__table__.c.id],
            update_columns=columns,
        )
    return await repo.bulk_update(
        data, update_columns={field.key: field for field in columns}
    )


async def test_defaults_patch_bulk_and_rollback(runtime):
    db, repo_type = runtime.db, runtime.repo_type
    async with db.uow() as unit, transaction():
        repo = repo_type(unit)
        first = await repo.create(ProbeEntity(code="a", quantity=1))
        assert first.id is not None and first.created_at is not None
        assert first.note == "fallback"
        data = [
            ProbeEntity(code="b", quantity=2, note=None),
            ProbeEntity(code="c", quantity=3),
        ]
        if runtime.backend in ("mysql", "mysql-orm"):
            columns = RepositoryProbeTable.__table__.c
            # Separate input shapes explicitly: NULL versus omitted default.
            assert (
                await repo.bulk_insert(
                    data[:1],
                    insert_columns={
                        "code": columns.code,
                        "quantity": columns.quantity,
                        "note": columns.note,
                    },
                )
                == 1
            )
            assert (
                await repo.bulk_insert(
                    data[1:],
                    insert_columns={
                        "code": columns.code,
                        "quantity": columns.quantity,
                    },
                )
                == 1
            )
        else:
            assert len(await repo.bulk_create(data)) == 2
        by_code = {row.code: row for row in await repo.get_all()}
        assert by_code["b"].note is None
        assert by_code["c"].note == "fallback"
        changed = await repo.update_by_id(first.id, {"note": None})
        if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
            assert changed == 1
            await unit.refresh(first)
            changed = await repo.get_by_id(first.id)
        assert changed.note is None and changed.quantity == 1
        assert changed.version_num == 2
        rows = await update_probe_batch(
            repo,
            [
                ProbeEntity.patch(
                    id=by_code["a"].id, quantity=10, attributes={"ok": True}
                ),
                ProbeEntity.patch(
                    id=by_code["b"].id, quantity=20, attributes={"ok": False}
                ),
            ],
            columns=[
                RepositoryProbeTable.__table__.c.quantity,
                RepositoryProbeTable.__table__.c.attributes,
            ],
        )
        if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
            assert rows == 2
            await unit.refresh(by_code["a"])
            await unit.refresh(by_code["b"])
            rows = await repo.get_by_ids([by_code["a"].id, by_code["b"].id])
        assert {row.quantity for row in rows} == {10, 20}
        assert {row.attributes["ok"] for row in rows} == {True, False}
        page = await repo.get_paged(1, 1)
        assert len(page.items) == 1 and page.total_items == 3
        assert len([row async for row in repo.get_all_stream(1)]) == 3
        removed = await repo.remove_by_ids([by_code["b"].id, by_code["c"].id])
        if runtime.backend in ("mysql", "mysql-orm"):
            assert removed == 2
        else:
            assert {row.code for row in removed} == {"b", "c"}
        assert await repo.get_by_id(by_code["b"].id) is None
    with pytest.raises(RuntimeError, match="rollback"):
        async with db.uow() as unit, transaction():
            await repo_type(unit).create(ProbeEntity(code="rolled-back"))
            raise RuntimeError("rollback")
    with pytest.raises(IntegrityError):
        async with db.uow() as unit, transaction():
            await repo_type(unit).create(ProbeEntity(code="a"))
    async with db.uow() as unit:
        assert [row.code for row in await repo_type(unit).get_all()] == ["a"]


async def test_native_upsert_and_explicit_update_expressions(runtime):
    if runtime.backend in ("mysql-orm", "oracle", "mssql"):
        pytest.skip("This path does not implement native upsert")
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        first = await repo.create(ProbeEntity(code="a", quantity=1))
        columns = RepositoryProbeTable.__table__.c
        options = {
            "update_columns": [columns.quantity],
            "changes": {
                columns.version_num: columns.version_num + 1,
                columns.updated_at: func.current_timestamp(),
            },
        }
        if runtime.backend in ("postgresql", "sqlite"):
            options["conflict_columns"] = [columns.code]
        await repo.upsert(
            ProbeEntity(id=first.id + 1000, code="a", quantity=9), **options
        )
        if runtime.backend == "mysql":
            await unit.refresh(first)
        updated = await repo.get_by_id(first.id)
        assert updated is not None
        assert updated.quantity == 9 and updated.version_num == 2
        await repo.bulk_upsert(
            [
                ProbeEntity(code="a", quantity=11),
                ProbeEntity(code="b", quantity=12),
            ],
            insert_columns={
                "code": columns.code,
                "quantity": columns.quantity,
            },
            **options,
        )
        if runtime.backend == "mysql":
            await unit.refresh(first)
        assert {row.quantity for row in await repo.get_all()} == {11, 12}


async def test_updates_and_deletes_issue_only_the_write_statement(runtime):
    statements = []
    event.listen(
        runtime.db.engine.sync_engine,
        "before_cursor_execute",
        lambda conn, cursor, statement, params, context, many: (
            statements.append((statement, context.isupdate, context.isdelete))
        ),
    )
    counts = runtime.backend in ("mysql", "mysql-orm", "mariadb")
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        record = await repo.create(ProbeEntity(code="a"))
        id = record.id
        for operation in (
            lambda: repo.update_by_id(id, {"quantity": 4}),
            lambda: repo.update_by_ids([id], {"quantity": 5}),
            lambda: repo.update_row_by_id(id, ProbeEntity.patch(quantity=6)),
            lambda: update_probe_batch(
                repo,
                [ProbeEntity.patch(id=id, quantity=7)],
                columns=[RepositoryProbeTable.__table__.c.quantity],
            ),
        ):
            statements.clear()
            result = await operation()
            assert len(statements) == 1
            assert statements[0][1]
            if counts:
                assert result == 1
        if counts:
            await unit.refresh(record)
        assert (await repo.get_by_id(id)).quantity == 7
        statements.clear()
        removed = await repo.remove_by_id(id)
        if runtime.backend in ("mysql", "mysql-orm"):
            assert removed == 1
        else:
            assert removed.id == id and removed.quantity == 7
        assert len(statements) == 1
        assert statements[0][2]
        statements.clear()
        missing = await repo.update_by_id(id, {"quantity": 5})
        assert missing == 0 if counts else missing is None
        assert len(statements) == 1
        assert statements[0][1]
        missing = await repo.remove_by_id(id)
        if runtime.backend in ("mysql", "mysql-orm"):
            assert missing == 0
        else:
            assert missing is None


async def test_base_and_timestamp_shapes_do_not_require_id(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/shapes.db",
        2,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    now = datetime(2025, 1, 1, tzinfo=UTC)
    try:
        async with db.engine.begin() as conn:
            await conn.run_sync(CodeTable.__table__.create)
            await conn.run_sync(DatedTable.__table__.create)
        async with db.uow() as unit, transaction():
            basic = CodeRepository(unit)
            dated = DatedRepository(unit)
            assert (
                await basic.create(CodeEntity(code="plain"))
            ).code == "plain"
            await dated.bulk_create(
                [
                    DatedEntity(
                        code=str(i), created_at=now + timedelta(days=i)
                    )
                    for i in range(3)
                ]
            )
            assert len([row async for row in basic.get_all_stream()]) == 1
            assert (
                await dated.get_paged_range(now, now + timedelta(days=1), 10)
            ).total_items == 2
            assert (await dated.get_paged_gt(now, 10)).total_items == 2
            assert (await dated.get_paged_ge(now, 10)).total_items == 3
            assert (await dated.get_paged_lt(now, 10)).total_items == 0
            assert (await dated.get_paged_le(now, 10)).total_items == 1
            assert len([row async for row in dated.get_stream_gt(now)]) == 2
    finally:
        await db.dispose()


@pytest.mark.parametrize(
    "repo_type,dialect,syntax",
    [
        (PGProbe, postgresql.dialect(), "RETURNING"),
        (SQLiteProbe, sqlite.dialect(), "RETURNING"),
        (MariaDBProbe, mysql.dialect(), "RETURNING"),
        (OracleProbe, oracle.dialect(), "RETURNING"),
        (MSSQLProbe, mssql.dialect(), "OUTPUT"),
    ],
)
async def test_native_insert_and_bulk_update_sql(repo_type, dialect, syntax):
    result = SimpleNamespace(
        scalar_one=lambda: ProbeEntity(code="a"),
        scalars=lambda: SimpleNamespace(all=lambda: []),
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repo = repo_type(SimpleNamespace(execute=session.execute))
    await repo.create(ProbeEntity(code="a"))
    stmt = session.execute.call_args.args[0]
    assert syntax in str(stmt.compile(dialect=dialect))
    await repo.bulk_create([ProbeEntity(code="a"), ProbeEntity(code="b")])
    stmt = session.execute.call_args.args[0]
    assert syntax in str(stmt.compile(dialect=dialect))
    if repo_type is not MariaDBProbe:
        await update_probe_batch(
            repo,
            [
                ProbeEntity.patch(id=1, quantity=3),
                ProbeEntity.patch(id=2, quantity=4),
            ],
            columns=[RepositoryProbeTable.__table__.c.quantity],
        )
        stmt = session.execute.call_args.args[0]
        assert "UPDATE" in str(stmt.compile(dialect=dialect))
        assert syntax in str(stmt.compile(dialect=dialect))


@pytest.mark.parametrize(
    "repo_type,dialect,syntax",
    [
        (PGProbe, postgresql.dialect(), "RETURNING"),
        (SQLiteProbe, sqlite.dialect(), "RETURNING"),
        (MariaDBProbe, mysql.dialect(), "RETURNING"),
        (OracleProbe, oracle.dialect(), "RETURNING"),
        (MSSQLProbe, mssql.dialect(), "OUTPUT"),
        (MySQLProbe, mysql.dialect(), None),
    ],
)
async def test_delete_uses_native_results_without_readback(
    repo_type, dialect, syntax
):
    row = ProbeEntity(id=1, code="deleted", quantity=5)
    result = SimpleNamespace(
        rowcount=1,
        scalar_one_or_none=lambda: row,
        scalars=lambda: SimpleNamespace(all=lambda: [row]),
    )
    # Only execute is available: there can be no ORM refresh or commit.
    unit = SimpleNamespace(execute=AsyncMock(return_value=result))
    repo = repo_type(unit)
    single = await repo.remove_by_id(1)
    unit.execute.assert_awaited_once()
    assert single == 1 if syntax is None else single is row
    unit.execute.reset_mock()
    batch = await repo.remove_by_ids([1, 2])
    unit.execute.assert_awaited_once()
    assert batch == 1 if syntax is None else batch == [row]
    stmt = unit.execute.call_args.args[0]
    sql = str(stmt.compile(dialect=dialect))
    assert "DELETE" in sql
    if syntax is None:
        assert not list(stmt.exported_columns)
        assert "RETURNING" not in sql and "OUTPUT" not in sql
    else:
        assert syntax in sql
        assert "code" in stmt.exported_columns


async def test_delete_returns_stored_values_and_caller_can_roll_back(runtime):
    counts = runtime.backend in ("mysql", "mysql-orm")
    async with runtime.db.uow() as unit:
        repo = runtime.repo_type(unit)
        first = await repo.create(ProbeEntity(code="first", quantity=1))
        second = await repo.create(ProbeEntity(code="second", quantity=2))
        first_id, second_id = first.id, second.id
        await unit.commit()
        first.quantity = 999  # Pending ORM state must not replace DB output.
        statements = []

        def capture(conn, cursor, statement, params, context, many):
            statements.append(statement)

        engine = runtime.db.engine.sync_engine
        event.listen(engine, "before_cursor_execute", capture)
        try:
            removed = await repo.remove_by_id(first_id)
            assert len(statements) == 1
            if counts:
                assert removed == 1
            else:
                assert (removed.id, removed.code, removed.quantity) == (
                    first_id,
                    "first",
                    1,
                )
            statements.clear()
            removed = await repo.remove_by_ids(
                [second_id, second_id, second_id + 100]
            )
            assert len(statements) == 1
            if counts:
                assert removed == 1
            else:
                assert [(row.id, row.quantity) for row in removed] == [
                    (second_id, 2)
                ]
            missing = await repo.remove_by_id(first_id)
            assert missing == 0 if counts else missing is None
            empty = await repo.remove_by_ids([])
            assert empty == 0 if counts else empty == []
            assert all(
                sql.lstrip().upper().startswith("DELETE") for sql in statements
            )
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert await repo.get_all() == []
        await unit.rollback()
        assert {row.code: row.quantity for row in await repo.get_all()} == {
            "first": 1,
            "second": 2,
        }


@pytest.mark.parametrize(
    "repo_type,dialect,options,syntax",
    [
        (
            PGProbe,
            postgresql.dialect(),
            {
                "conflict_columns": [RepositoryProbeTable.__table__.c.code],
                "update_columns": [RepositoryProbeTable.__table__.c.quantity],
            },
            "ON CONFLICT",
        ),
        (
            SQLiteProbe,
            sqlite.dialect(),
            {
                "conflict_columns": [RepositoryProbeTable.__table__.c.code],
                "update_columns": [RepositoryProbeTable.__table__.c.quantity],
            },
            "ON CONFLICT",
        ),
        (
            MySQLProbe,
            mysql.dialect(),
            {"update_columns": [RepositoryProbeTable.__table__.c.quantity]},
            "ON DUPLICATE KEY UPDATE",
        ),
        (
            MariaDBProbe,
            mysql.dialect(),
            {"update_columns": [RepositoryProbeTable.__table__.c.quantity]},
            "ON DUPLICATE KEY UPDATE",
        ),
    ],
)
async def test_native_bulk_upsert_sql(
    repo_type, dialect, options, syntax, monkeypatch
):
    result = SimpleNamespace(
        rowcount=2,
        scalars=lambda: SimpleNamespace(all=lambda: []),
        scalar_one=lambda: ProbeEntity(code="a", quantity=1),
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    repo = repo_type(SimpleNamespace(execute=session.execute))
    data = [
        ProbeEntity(code="a", quantity=1),
        ProbeEntity(code="b", quantity=2),
    ]
    columns = RepositoryProbeTable.__table__.c
    insert_columns = {"code": columns.code, "quantity": columns.quantity}
    stmt = repo._bulk_upsert_stmt(
        [item.to_row() for item in data],
        insert_columns=insert_columns,
        **options,
    ).prefix_with("/* custom batch */")
    session.execute.assert_not_awaited()
    monkeypatch.setattr(
        repo, "_bulk_upsert_stmt", lambda *args, **kwargs: stmt
    )
    await repo.bulk_upsert(data, insert_columns=insert_columns, **options)
    session.execute.assert_awaited_once()
    executed = session.execute.call_args.args[0]
    assert syntax in str(executed.compile(dialect=dialect))
    assert "/* custom batch */" in str(executed.compile(dialect=dialect))
    session.execute.reset_mock()
    bulk = AsyncMock(side_effect=AssertionError("single called bulk"))
    monkeypatch.setattr(repo, "bulk_upsert", bulk)
    monkeypatch.setattr(repo, "_bulk_upsert_stmt", bulk)
    await repo.upsert(data[0], **options)
    session.execute.assert_awaited_once()
    assert "custom batch" not in str(session.execute.call_args.args[0])
    bulk.assert_not_called()


async def test_overriding_bulk_update_builder_changes_public_write(runtime):
    class FilteredRepository(runtime.repo_type):
        def _bulk_update_stmt(self, data, **options):
            stmt = super()._bulk_update_stmt(data, **options)
            return stmt.where(RepositoryProbeTable.quantity < 5)

    async with runtime.db.uow() as unit, transaction():
        repo = FilteredRepository(unit)
        first = await repo.create(ProbeEntity(code="a", quantity=1))
        second = await repo.create(ProbeEntity(code="b", quantity=10))
        await update_probe_batch(
            repo,
            [
                ProbeEntity.patch(id=first.id, quantity=20),
                ProbeEntity.patch(id=second.id, quantity=30),
            ],
            columns=[RepositoryProbeTable.__table__.c.quantity],
        )
        if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
            await unit.refresh(first)
            await unit.refresh(second)
        assert {row.code: row.quantity for row in await repo.get_all()} == {
            "a": 20,
            "b": 10,
        }


@pytest.mark.parametrize(
    "repo_type,dialect",
    [
        (PGProbe, postgresql.dialect()),
        (SQLiteProbe, sqlite.dialect()),
        (MySQLProbe, mysql.dialect()),
        (MariaDBProbe, mysql.dialect()),
        (OracleProbe, oracle.dialect()),
        (MSSQLProbe, mssql.dialect()),
    ],
)
def test_bulk_update_builder_leaves_result_and_session_policy_to_caller(
    repo_type, dialect
):
    repo = repo_type(None)
    columns = RepositoryProbeTable.__table__.c
    if repo_type is PGProbe:
        stmt = repo._bulk_update_stmt(
            [{"id": 1, "quantity": 7}],
            key_columns=[columns.id],
            update_columns=[columns.quantity],
        )
    else:
        stmt = repo._bulk_update_stmt(
            [ProbeEntity.patch(id=1, quantity=7)],
            update_columns={"quantity": columns.quantity},
        )
    assert not stmt.get_execution_options()
    if dialect.update_returning:
        stmt = stmt.returning(columns.quantity)
        assert list(stmt.exported_columns.keys()) == ["quantity"]
    # A caller can choose its own session policy without hidden result columns.
    stmt = stmt.execution_options(synchronize_session=False)
    assert "UPDATE" in str(stmt.compile(dialect=dialect))
    sql = str(stmt.compile(dialect=dialect)).upper()
    assert "CASE" not in sql
    assert "VALUES" in sql or "SELECT" in sql


async def test_grid_update_preserves_nulls_and_does_not_touch_unmatched_rows(
    runtime,
):
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        data = [ProbeEntity(code=code, quantity=1) for code in ("a", "b", "c")]
        if runtime.backend in ("mysql", "mysql-orm"):
            columns = RepositoryProbeTable.__table__.c
            assert (
                await repo.bulk_insert(
                    data,
                    insert_columns={
                        "code": columns.code,
                        "quantity": columns.quantity,
                    },
                )
                == 3
            )
            created = await repo.get_all()
        else:
            created = await repo.bulk_create(data)
        by_code = {row.code: row for row in created}
        first, second, untouched = (by_code[code] for code in ("a", "b", "c"))
        columns = RepositoryProbeTable.__table__.c
        result = await update_probe_batch(
            repo,
            [
                ProbeEntity.patch(
                    id=first.id, quantity=3, note=None, attributes=None
                ),
                ProbeEntity.patch(
                    id=second.id,
                    quantity=4,
                    note="second",
                    attributes={"text": "متن" * 5000},
                ),
                ProbeEntity.patch(
                    id=max(first.id, second.id, untouched.id) + 100,
                    quantity=99,
                    note="missing",
                    attributes={},
                ),
            ],
            columns=[columns.quantity, columns.note, columns.attributes],
        )
        if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
            assert result == 2
        else:
            assert {row.id for row in result} == {first.id, second.id}
        stmt = select(
            columns.code, columns.quantity, columns.note, columns.attributes
        ).order_by(columns.code)
        assert (await unit.execute(stmt)).all() == [
            ("a", 3, None, None),
            ("b", 4, "second", {"text": "متن" * 5000}),
            ("c", 1, "fallback", None),
        ]


async def test_large_json_create_and_returning_preserve_complete_values(
    runtime,
):
    payload = {"text": "متن" * 5000}
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        single = await repo.create(ProbeEntity(code="one", attributes=payload))
        data = [ProbeEntity(code="two", attributes=payload)]
        if runtime.backend in ("mysql", "mysql-orm"):
            columns = RepositoryProbeTable.__table__.c
            assert (
                await repo.bulk_insert(
                    data,
                    insert_columns={
                        "code": columns.code,
                        "attributes": columns.attributes,
                    },
                )
                == 1
            )
            batch = [row for row in await repo.get_all() if row.code == "two"]
        else:
            batch = await repo.bulk_create(data)
        assert single.attributes == payload
        assert batch[0].attributes == payload
        updated = await repo.update_by_id(single.id, {"attributes": null()})
        if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
            assert updated == 1
            await unit.refresh(single)
        else:
            assert updated is single
        assert single.attributes is None


async def test_mysql_bulk_insert_returns_driver_count_without_refresh():
    execute = AsyncMock(return_value=SimpleNamespace(rowcount=7))
    repo = MySQLProbe(SimpleNamespace(execute=execute))
    columns = RepositoryProbeTable.__table__.c
    assert (
        await repo.bulk_insert([], insert_columns={"code": columns.code}) == 0
    )
    execute.assert_not_awaited()
    count = await repo.bulk_insert(
        [ProbeEntity(code="a"), ProbeEntity(code="b")],
        insert_columns={"code": columns.code},
    )
    assert count == 7
    execute.assert_awaited_once()
    stmt = execute.call_args.args[0]
    assert not stmt.get_execution_options()
    assert not list(stmt.exported_columns)


async def test_replacing_bulk_update_builder_preserves_public_write_policy(
    runtime,
):
    class CustomRepository(runtime.repo_type):
        def _bulk_update_stmt(self, data, **options):
            return update(RepositoryProbeTable).values(quantity=42)

    async with runtime.db.uow() as unit, transaction():
        repo = CustomRepository(unit)
        row = await repo.create(ProbeEntity(code="custom", quantity=1))
        statements = []

        def capture(conn, cursor, statement, parameters, context, many):
            statements.append(statement)

        event.listen(
            runtime.db.engine.sync_engine, "before_cursor_execute", capture
        )
        try:
            result = await update_probe_batch(
                repo,
                [ProbeEntity.patch(id=row.id, quantity=2)],
                columns=[RepositoryProbeTable.__table__.c.quantity],
            )
            if runtime.backend in ("mysql", "mysql-orm", "mariadb"):
                assert result == 1
                assert row.quantity == 1
            else:
                assert result == [row]
                assert row.quantity == 42
        finally:
            event.remove(
                runtime.db.engine.sync_engine, "before_cursor_execute", capture
            )
        assert len(statements) == 1
        assert statements[0].lstrip().upper().startswith("UPDATE")


async def test_postgresql_values_grid_supports_custom_join_without_id(runtime):
    if runtime.backend != "postgresql":
        pytest.skip("PostgreSQL VALUES relation")
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        await repo.create(ProbeEntity(code="a", quantity=1))
        grid = repo._values_grid(
            [{"code": "a", "attributes": {"ok": True}}],
            columns=[
                RepositoryProbeTable.__table__.c.code,
                RepositoryProbeTable.__table__.c.attributes,
            ],
        )
        stmt = select(grid.c.attributes).join_from(
            RepositoryProbeTable,
            grid,
            RepositoryProbeTable.code == grid.c.code,
        )
        result = await unit.session.execute(stmt)
        assert result.scalar_one() == {"ok": True}


@pytest.mark.parametrize(
    "repo_type,uow_factory",
    [
        (PGProbe, PGUnitOfWork),
        (MySQLProbe, MySQLUnitOfWork),
        (MariaDBProbe, MariaDBUnitOfWork),
        (SQLiteProbe, SQLiteUnitOfWork),
        (OracleProbe, OracleUnitOfWork),
        (MSSQLProbe, MSSQLUnitOfWork),
    ],
)
@pytest.mark.parametrize(
    "read", ["get_by_id", "get_by_ids", "get_all", "stream"]
)
async def test_reads_preserve_pending_orm_changes(
    tmp_path, repo_type, uow_factory, read
):
    # Exercise each backend's portable SELECT on SQLite, without native DML.
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/reads.db",
        2,
        0,
        5,
        1800,
        uow_factory=uow_factory,
    )
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(RepositoryProbeTable.__table__.create)
        async with db.uow() as unit:
            row = RepositoryProbeTable(code="pending", quantity=1)
            unit.session.add(row)
            await unit.commit()
            repo = repo_type(unit)
            row.quantity = 9
            statements = []

            def capture(conn, cursor, statement, parameters, context, many):
                statements.append(statement)

            event.listen(
                db.engine.sync_engine, "before_cursor_execute", capture
            )
            try:
                if read == "get_by_id":
                    found = [await repo.get_by_id(row.id)]
                elif read == "get_by_ids":
                    found = await repo.get_by_ids([row.id])
                elif read == "get_all":
                    found = await repo.get_all()
                else:
                    found = [item async for item in repo.get_all_stream()]
            finally:
                event.remove(
                    db.engine.sync_engine, "before_cursor_execute", capture
                )
            assert found[0] is row
            assert row.quantity == 9
            assert row in unit.session.dirty
            assert len(statements) == 1
            assert statements[0].lstrip().upper().startswith("SELECT")
            await unit.commit()
        async with db.session_factory() as observer:
            stored = (
                await observer.scalars(select(RepositoryProbeTable))
            ).one()
            assert stored.quantity == 9
    finally:
        await db.dispose()


async def test_upsert_batch_preserves_explicit_nullable_values(runtime):
    if runtime.backend in ("mysql-orm", "oracle", "mssql"):
        pytest.skip("This path does not implement native upsert")
    columns = RepositoryProbeTable.__table__.c
    options = {"update_columns": [columns.quantity, columns.note]}
    if runtime.backend in ("postgresql", "sqlite"):
        options["conflict_columns"] = [columns.code]
    async with runtime.db.uow() as unit, transaction():
        repo = runtime.repo_type(unit)
        data = [
            ProbeEntity(code="a", note="old a"),
            ProbeEntity(code="b", note="old b"),
        ]
        if runtime.backend == "mysql":
            assert (
                await repo.bulk_insert(
                    data,
                    insert_columns={
                        "code": columns.code,
                        "note": columns.note,
                    },
                )
                == 2
            )
        else:
            await repo.bulk_create(data)
        await repo.bulk_upsert(
            [
                ProbeEntity(code="a", quantity=1, note=None),
                ProbeEntity(code="b", quantity=2, note="new b"),
            ],
            insert_columns={
                "code": columns.code,
                "quantity": columns.quantity,
                "note": columns.note,
            },
            **options,
        )
        stmt = select(columns.code, columns.quantity, columns.note).order_by(
            columns.code
        )
        assert (await unit.execute(stmt)).all() == [
            ("a", 1, None),
            ("b", 2, "new b"),
        ]
        for rows in (
            [
                ProbeEntity(code="a", quantity=3),
                ProbeEntity(code="b", quantity=4, note="must not disappear"),
            ],
            [
                ProbeEntity(code="a", quantity=3, note="must not disappear"),
                ProbeEntity(code="b", quantity=4),
            ],
        ):
            with pytest.raises(KeyError, match="note"):
                await repo.bulk_upsert(
                    rows,
                    insert_columns={
                        "code": columns.code,
                        "quantity": columns.quantity,
                        "note": columns.note,
                    },
                    **options,
                )
        assert (await unit.execute(stmt)).all() == [
            ("a", 1, None),
            ("b", 2, "new b"),
        ]
