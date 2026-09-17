"""Public field options work with native repository writes and SQL names."""

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from papilio.infra.db.connection import DBConnection
from papilio.infra.db.repositories.backends.mariadb import (
    MariaDBIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.mysql import (
    MySQLIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.postgresql import (
    PGIdentifiedRepository,
)
from papilio.infra.db.repositories.backends.sqlite import (
    SQLiteIdentifiedRepository,
)
from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.schema.fields import CharField, IntField, JSONField
from papilio.infra.db.table import BaseTable
from papilio.infra.db.uow import (
    MariaDBUnitOfWork,
    MySQLUnitOfWork,
    PGUnitOfWork,
    SQLiteUnitOfWork,
)


class FieldMappingEntity(IdentifiedEntity):
    code: str = CharField(40, unique=True, db_column="external_code")
    amount: int = IntField(default=0, db_column="stored_amount")
    payload: dict | None = JSONField(
        default_factory=dict,
        db_column="stored_payload",
    )
    sql_payload: dict | None = JSONField(
        default=None,
        nullable=True,
        none_as_null=True,
    )


class FieldMappingTable(FieldMappingEntity, BaseTable, table=True):
    pass


@pytest.fixture(
    params=[
        ("sqlite", SQLiteUnitOfWork, SQLiteIdentifiedRepository),
        ("mysql-orm", MySQLUnitOfWork, MySQLIdentifiedRepository),
        ("postgresql", PGUnitOfWork, PGIdentifiedRepository),
        ("mysql", MySQLUnitOfWork, MySQLIdentifiedRepository),
        ("mariadb", MariaDBUnitOfWork, MariaDBIdentifiedRepository),
    ]
)
async def field_store(request, tmp_path):
    backend, unit_type, repo_type = request.param
    dsn = (
        f"sqlite+aiosqlite:///{tmp_path}/fields.db"
        if backend in ("sqlite", "mysql-orm")
        else os.getenv(f"PAPILIO_TEST_{backend.upper()}")
    )
    if not dsn:
        pytest.skip(
            f"Set PAPILIO_TEST_{backend.upper()} for live backend tests"
        )

    class Repository(repo_type[FieldMappingEntity]):
        table = FieldMappingTable

    db = DBConnection(dsn, 1, 0, 5, 1800, uow_factory=unit_type)
    created = False
    try:
        async with db.engine.begin() as connection:
            await connection.run_sync(FieldMappingTable.__table__.create)
            created = True
        async with db.uow() as unit:
            yield SimpleNamespace(
                backend=backend, repo=Repository(unit), unit=unit
            )
    finally:
        if created:
            async with db.engine.begin() as connection:
                await connection.run_sync(FieldMappingTable.__table__.drop)
        await db.dispose()


async def test_create_preserves_json_null_and_sql_null(field_store):
    repo, unit = field_store.repo, field_store.unit
    await repo.create(
        FieldMappingEntity(code="one", payload=None, sql_payload=None)
    )
    data = [
        FieldMappingEntity(code="two", payload=None, sql_payload=None),
        FieldMappingEntity(
            code="three", payload={"ok": True}, sql_payload=None
        ),
    ]
    columns = FieldMappingTable.__table__.c
    if field_store.backend in ("mysql", "mysql-orm"):
        assert (
            await repo.bulk_insert(
                data,
                insert_columns={
                    "code": columns.external_code,
                    "payload": columns.stored_payload,
                    "sql_payload": columns.sql_payload,
                },
            )
            == 2
        )
    else:
        await repo.bulk_create(data)
    stmt = select(
        columns.external_code,
        columns.stored_payload.is_(None),
        columns.sql_payload.is_(None),
    ).order_by(columns.external_code)
    assert (await unit.execute(stmt)).all() == [
        ("one", False, True),
        ("three", False, True),
        ("two", False, True),
    ]


async def test_upserts_and_batch_updates_use_explicit_field_names(field_store):
    if field_store.backend == "mysql-orm":
        pytest.skip("Only the ORM create path runs on SQLite for MySQL")
    repo, unit = field_store.repo, field_store.unit
    columns = FieldMappingTable.__table__.c
    options = {"update_columns": [columns.stored_amount]}
    if field_store.backend in ("sqlite", "postgresql"):
        options["conflict_columns"] = [columns.external_code]
    await repo.upsert(FieldMappingEntity(code="a", amount=1), **options)
    await repo.bulk_upsert(
        [
            FieldMappingEntity(code="a", amount=2),
            FieldMappingEntity(code="b", amount=3),
        ],
        insert_columns={
            "code": columns.external_code,
            "amount": columns.stored_amount,
        },
        **options,
    )
    stmt = select(columns.external_code, columns.stored_amount).order_by(
        columns.external_code
    )
    assert (await unit.execute(stmt)).all() == [("a", 2), ("b", 3)]
    stmt = select(columns.id).where(columns.external_code == "a")
    id = (await unit.execute(stmt)).scalar_one()
    if field_store.backend == "postgresql":
        await repo.bulk_update(
            [{"id": id, "stored_amount": 7}],
            key_columns=[columns.id],
            update_columns=[columns.stored_amount],
        )
    else:
        await repo.bulk_update(
            [FieldMappingEntity.patch(id=id, amount=7)],
            update_columns={"amount": columns.stored_amount},
        )
    stmt = select(columns.stored_amount).where(columns.id == id)
    assert (await unit.execute(stmt)).scalar_one() == 7


async def test_mysql_bulk_insert_uses_column_mapping_and_rolls_back(
    field_store,
):
    if field_store.backend not in ("mysql", "mysql-orm"):
        pytest.skip("MySQL count-returning INSERT")
    repo, unit = field_store.repo, field_store.unit
    columns = FieldMappingTable.__table__.c
    selected = {
        "code": columns.external_code,
        "amount": columns.stored_amount,
        "payload": columns.stored_payload,
        "sql_payload": columns.sql_payload,
    }
    statements = []

    def capture(conn, cursor, statement, parameters, context, many):
        statements.append(context.isinsert)

    engine = unit.connection.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        count = await repo.bulk_insert(
            [
                FieldMappingEntity(
                    code="one", amount=1, payload=None, sql_payload=None
                ),
                FieldMappingEntity(
                    code="two",
                    amount=2,
                    payload={"ok": True},
                    sql_payload={"ok": False},
                ),
            ],
            insert_columns=selected,
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert count == 2
    assert statements == [True]
    assert not unit.session.identity_map
    stmt = select(
        columns.external_code,
        columns.stored_amount,
        columns.stored_payload,
        columns.sql_payload,
    ).order_by(columns.external_code)
    assert (await unit.execute(stmt)).all() == [
        ("one", 1, None, None),
        ("two", 2, {"ok": True}, {"ok": False}),
    ]
    # Failed batches raise instead of reporting their input length as success.
    with pytest.raises(IntegrityError):
        await repo.bulk_insert(
            [FieldMappingEntity(code="one"), FieldMappingEntity(code="three")],
            insert_columns={"code": columns.external_code},
        )
    await unit.rollback()
    assert (await unit.execute(stmt)).all() == []
