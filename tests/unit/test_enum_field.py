from enum import StrEnum

import pytest
from sqlalchemy import create_engine, insert, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable
from sqlalchemy.types import Enum as SAEnum
from sqlmodel import Session, select

from papilio.infra.db.schema.entity import IdentifiedEntity
from papilio.infra.db.schema.fields import EnumField
from papilio.infra.db.table import BaseTable


class Kind(StrEnum):
    EARNING = "earning"
    DEDUCTION = "deduction"


class TextEnumRow(IdentifiedEntity, BaseTable, table=True):
    table_name = "enum_text_probe"

    kind: Kind = EnumField(
        Kind,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
        length=35,
        default=Kind.EARNING,
    )
    optional_kind: Kind | None = EnumField(
        Kind,
        native_enum=False,
        values_callable=lambda members: [member.value for member in members],
        nullable=True,
        default=None,
    )


class NativeEnumRow(IdentifiedEntity, BaseTable, table=True):
    table_name = "enum_native_probe"
    kind: Kind = EnumField(Kind)


@pytest.fixture
def engine():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE enum_text_probe (id INTEGER PRIMARY KEY, "
                "kind VARCHAR(35) NOT NULL, optional_kind VARCHAR(9))"
            )
        )
    try:
        yield engine
    finally:
        engine.dispose()


def test_text_mapping_keeps_postgresql_varchar_without_enum_constraint():
    ddl = str(
        CreateTable(TextEnumRow.__table__).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "kind VARCHAR(35) NOT NULL" in ddl
    assert "optional_kind VARCHAR(9)" in ddl
    assert "CHECK" not in ddl


def test_existing_text_rows_load_members_without_serialization_warning(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO enum_text_probe (id, kind, optional_kind) "
                "VALUES (1, 'earning', 'deduction')"
            )
        )
    with Session(engine) as session:
        row = session.exec(select(TextEnumRow)).one()
        assert row.kind is Kind.EARNING
        assert row.optional_kind is Kind.DEDUCTION
        assert row.model_dump(mode="json", warnings="error") == {
            "id": 1,
            "kind": "earning",
            "optional_kind": "deduction",
        }


@pytest.mark.parametrize("value", [Kind.DEDUCTION, "deduction"])
def test_writes_store_values_and_reads_restore_members(engine, value):
    with engine.begin() as connection:
        connection.execute(insert(TextEnumRow).values(id=1, kind=value))
        stored = connection.execute(
            text("SELECT kind, optional_kind FROM enum_text_probe")
        ).one()
        assert tuple(stored) == ("deduction", None)
    with Session(engine) as session:
        row = session.exec(select(TextEnumRow)).one()
        assert row.kind is Kind.DEDUCTION
        assert row.optional_kind is None
        row.model_dump(warnings="error")


def test_enum_default_and_nullable_field_round_trip(engine):
    with engine.begin() as connection:
        connection.execute(insert(TextEnumRow).values(id=1))
    with Session(engine) as session:
        row = session.exec(select(TextEnumRow)).one()
        assert row.kind is Kind.EARNING
        assert row.optional_kind is None


def test_unknown_stored_value_is_rejected_without_rewriting_it(engine):
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO enum_text_probe (id, kind) VALUES (1, 'bad')")
        )
    with Session(engine) as session:
        with pytest.raises(LookupError, match="bad"):
            session.exec(select(TextEnumRow)).one()
    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT kind FROM enum_text_probe")
            ).scalar_one()
            == "bad"
        )


def test_default_mapping_preserves_native_enum_and_member_names():
    column_type = NativeEnumRow.__table__.c.kind.type
    assert isinstance(column_type, SAEnum)
    assert column_type.native_enum is True
    assert column_type.enums == ["EARNING", "DEDUCTION"]
    bind = column_type.bind_processor(postgresql.dialect())
    read = column_type.result_processor(postgresql.dialect(), None)
    assert bind is not None
    assert read is not None
    assert bind(Kind.EARNING) == "EARNING"
    assert read("EARNING") is Kind.EARNING


@pytest.mark.parametrize("length", [0, 3, 8])
def test_length_shorter_than_stored_values_is_rejected(length):
    with pytest.raises(ValueError, match="length"):
        EnumField(
            Kind,
            native_enum=False,
            values_callable=lambda members: [
                member.value for member in members
            ],
            length=length,
        )
