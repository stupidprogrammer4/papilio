import os
from datetime import time
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable
from sqlmodel import Session

from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.schema.fields import TimeField
from papilio.infra.db.table import BaseTable


class ClockModel(IdentifiedEntity):
    opens_at: time = TimeField(db_column="opening_time", index=True)
    closes_at: time | None = TimeField(nullable=True, default=None)
    default_time: time = TimeField(default=time(9, 30))
    factory_time: time = TimeField(default_factory=lambda: time(10, 15))
    server_time: time = TimeField(server_default="07:45:00")


class ClockTable(ClockModel, BaseTable, table=True):
    pass


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request):
    backend = request.param
    schema = None
    if backend == "sqlite":
        engine = create_engine("sqlite://")
    else:
        dsn = os.getenv("PAPILIO_TEST_POSTGRESQL")
        if not dsn:
            pytest.skip(
                "Set PAPILIO_TEST_POSTGRESQL for live time-field tests"
            )
        url = make_url(dsn).set(drivername="postgresql+psycopg2")
        engine = create_engine(url)
        schema = "test_time_field_" + uuid4().hex
    try:
        if schema is not None:
            with engine.begin() as connection:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            engine.update_execution_options(
                schema_translate_map={None: schema}
            )
        ClockTable.__table__.create(engine)
        yield engine
    finally:
        if schema is not None:
            with engine.begin() as connection:
                connection.execute(
                    text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
                )
        engine.dispose()


def test_postgresql_clock_column_has_no_date_or_timezone():
    ddl = str(
        CreateTable(ClockTable.__table__).compile(dialect=postgresql.dialect())
    )
    assert "opening_time TIME WITHOUT TIME ZONE NOT NULL" in ddl
    assert "closes_at TIME WITHOUT TIME ZONE," in ddl
    assert (
        "server_time TIME WITHOUT TIME ZONE DEFAULT '07:45:00' NOT NULL" in ddl
    )
    assert "TIMESTAMP" not in ddl
    assert any(
        "opening_time" in index.columns
        for index in ClockTable.__table__.indexes
    )


@pytest.mark.parametrize(
    "clock", [time.min, time(13, 45, 21, 123456), time.max]
)
def test_clock_roundtrip_preserves_precision_and_serialization(engine, clock):
    with engine.begin() as connection:
        connection.execute(
            insert(ClockTable.__table__).values(
                id=1, opening_time=clock, closes_at=clock
            )
        )
    with Session(engine) as session:
        row = session.execute(select(ClockTable)).scalar_one()
        assert row.opens_at == clock
        assert row.closes_at == clock
        assert row.opens_at.tzinfo is None
        assert row.default_time == time(9, 30)
        assert row.factory_time == time(10, 15)
        assert row.server_time == time(7, 45)
        dumped = row.model_dump(mode="json", warnings="error")
        assert dumped["opens_at"] == clock.isoformat()
        assert ClockModel.model_validate(dumped).opens_at == clock


def test_orm_writes_and_nullable_clock_roundtrip(engine):
    with Session(engine) as session:
        row = ClockTable(opens_at=time(8), server_time=time(7))
        session.add(row)
        session.commit()
    with Session(engine) as session:
        row = session.execute(select(ClockTable)).scalar_one()
        assert row.opens_at == time(8)
        assert row.closes_at is None
        row.opens_at = time(16, 30)
        row.closes_at = time(20)
        session.commit()
    with Session(engine) as session:
        row = session.execute(select(ClockTable)).scalar_one()
        assert row.opens_at == time(16, 30)
        assert row.closes_at == time(20)


def test_server_default_is_used_by_raw_sql(engine):
    schema = (
        engine.get_execution_options()
        .get("schema_translate_map", {})
        .get(None)
    )
    name = ClockTable.__table__.name
    target = f'"{schema}"."{name}"' if schema else f'"{name}"'
    with engine.begin() as connection:
        connection.execute(
            text(
                f"INSERT INTO {target} "
                "(id, opening_time, default_time, factory_time) "
                "VALUES (1, '08:00:00', '09:30:00', '10:15:00')"
            )
        )
    with Session(engine) as session:
        row = session.execute(select(ClockTable)).scalar_one()
        assert row.server_time == time(7, 45)
        assert row.closes_at is None


def test_null_required_clock_fails_without_persisting_row(engine):
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(ClockTable.__table__).values(id=1, opening_time=None)
            )
    with engine.connect() as connection:
        assert connection.execute(select(ClockTable)).all() == []


def test_model_defaults_and_clock_input_parsing():
    row = ClockModel.model_validate(
        {"opens_at": "08:30:00", "server_time": "07:45:00"}
    )
    assert row.opens_at == time(8, 30)
    assert row.closes_at is None
    assert row.default_time == time(9, 30)
    assert row.factory_time == time(10, 15)


@pytest.mark.parametrize("value", [None, "24:00:00", "12:60:00", "not a time"])
def test_invalid_clock_input_is_rejected(value):
    with pytest.raises(ValidationError):
        ClockModel.model_validate(
            {"opens_at": value, "server_time": "07:45:00"}
        )


def test_required_clock_input_cannot_be_omitted():
    with pytest.raises(ValidationError):
        ClockModel.model_validate({"server_time": "07:45:00"})
