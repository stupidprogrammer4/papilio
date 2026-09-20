"""Conflict translation is optional and does not own transaction cleanup."""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import CheckConstraint, ForeignKey, insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.tools.conflicts import handle_conflicts
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork
from papilio.tools.checks import Checks


def unit(backend="postgresql"):
    return UnitOfWork(
        SimpleNamespace(backend=backend, session_factory=lambda: AsyncMock())
    )


def unique_error(detail="Key (email)=(a@example.com) already exists."):
    cause = SimpleNamespace(sqlstate="23505", detail=detail)
    return IntegrityError("INSERT", {}, SimpleNamespace(__cause__=cause))


@pytest.mark.parametrize("factory", [handle_conflicts, handle_conflicts()])
async def test_both_forms_preserve_call_result_and_metadata(factory):
    async def operation(value: int, *, increment: int = 1) -> int:
        """Preserved documentation."""
        return value + increment

    wrapped = factory(operation)
    assert inspect.signature(wrapped) == inspect.signature(operation)
    assert wrapped.__name__ == operation.__name__
    assert wrapped.__doc__ == operation.__doc__
    assert inspect.unwrap(wrapped) is operation
    async with unit():
        assert await wrapped(3, increment=2) == 5


@pytest.mark.parametrize("factory", [handle_conflicts, handle_conflicts()])
def test_sync_and_generators_rejected_at_decoration(factory):
    async def generator():
        yield 1

    for function in (lambda: None, generator):
        with pytest.raises(TypeError, match="async function"):
            factory(function)


async def test_missing_closed_or_unsupported_unit_fails_before_call():
    @handle_conflicts
    async def operation():
        pytest.fail("Missing backend must fail before side effects")

    with pytest.raises(RuntimeError, match="open UnitOfWork"):
        await operation()
    async with unit():
        pass
    with pytest.raises(RuntimeError, match="open UnitOfWork"):
        await operation()
    async with unit("unsupported"):
        with pytest.raises(NotImplementedError, match="unsupported"):
            await operation()


@pytest.mark.parametrize(
    "options,expected_message,expected_code",
    [
        ({}, "A record with these values already exists.", "conflict"),
        (
            {"entity": "User"},
            "User already exists with the same email.",
            "conflict",
        ),
        ({"entity": "User", "message": "Duplicate"}, "Duplicate", "conflict"),
        (
            {"message_code": "user.duplicate"},
            "A record with these values already exists.",
            "user.duplicate",
        ),
        ({"message": "", "message_code": ""}, "", ""),
    ],
)
async def test_defaults_overrides_cause_and_schema(
    options, expected_message, expected_code
):
    error = unique_error()

    @handle_conflicts(**options)
    async def operation():
        raise error

    async with unit():
        with pytest.raises(ConflictException) as caught:
            await operation()
    conflict = caught.value
    assert conflict.__cause__ is error
    assert conflict.status_code == 409
    assert conflict.as_schema().model_dump() == {
        "message": expected_message,
        "message_code": expected_code,
        "unique_dict": {"email": "a@example.com"},
    }


async def test_model_name_and_missing_details():
    class User:
        pass

    @handle_conflicts(entity=User)
    async def operation():
        raise unique_error("localized or unavailable")

    async with unit():
        with pytest.raises(ConflictException) as caught:
            await operation()
    assert caught.value.message == "User already exists."
    assert caught.value.unique_dict == {}


async def test_checks_receiver_inherited_keyword_and_explicit_entity():
    class Service(Checks):
        entity = "User"

        @handle_conflicts
        async def create(self):
            raise unique_error()

        @handle_conflicts(entity="Account")
        async def overridden(self):
            raise unique_error()

    class Child(Service):
        entity = "Customer"

    class Override(Service):
        entity = "Account holder"

        async def create(self):
            return await super().create()

    async with unit():
        for call, label in (
            (Service().create, "User"),
            (Child().create, "Customer"),
            (Override().create, "Account holder"),
            (lambda: Service.create(self=Service()), "User"),
            (Service().overridden, "Account"),
        ):
            with pytest.raises(ConflictException) as caught:
                await call()
            assert (
                caught.value.message
                == f"{label} already exists with the same email."
            )


async def test_checks_argument_is_not_mistaken_for_bound_receiver():
    class Service(Checks):
        entity = "Do not use this label"

        @staticmethod
        @handle_conflicts
        async def create(data):
            raise unique_error()

    @handle_conflicts
    async def create(data):
        raise unique_error()

    async with unit():
        for call in (create, Service.create):
            with pytest.raises(ConflictException) as caught:
                await call(Service())
            assert (
                caught.value.message
                == "A record with these values already exists."
            )


@pytest.mark.parametrize(
    "error",
    [
        IntegrityError("stmt", {}, SimpleNamespace(sqlstate="23503")),
        IntegrityError("stmt", {}, SimpleNamespace(sqlstate="23514")),
        IntegrityError("stmt", {}, SimpleNamespace(sqlstate="23502")),
        IntegrityError("stmt", {}, Exception("unknown")),
        ConflictException("Already translated", "conflict", {}),
        ValueError("unrelated"),
        asyncio.CancelledError(),
    ],
)
async def test_other_failures_are_preserved(error):
    @handle_conflicts
    async def operation():
        raise error

    async with unit():
        with pytest.raises(type(error)) as caught:
            await operation()
    assert caught.value is error


async def test_backend_selection_uses_each_call_and_active_unit():
    @handle_conflicts
    async def operation():
        await asyncio.sleep(0)
        raise unique_error()

    async def call(backend, exception):
        async with unit(backend):
            with pytest.raises(exception):
                await operation()

    await asyncio.gather(
        call("postgresql", ConflictException), call("sqlite", IntegrityError)
    )
    async with unit("postgresql") as first, unit("sqlite"):
        with first.activate():
            with pytest.raises(ConflictException):
                await operation()
        with pytest.raises(IntegrityError):
            await operation()


async def test_backend_is_captured_before_exception_unwinding():
    async with unit("postgresql") as current:

        @handle_conflicts
        async def operation():
            # Simulate scope cleanup before the error reaches the wrapper.
            await current.close()
            raise unique_error()

        with pytest.raises(ConflictException):
            await operation()


class Base(DeclarativeBase):
    pass


class Record(Base):
    __tablename__ = "conflict_records"
    __table_args__ = (CheckConstraint("quantity >= 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(unique=True)
    quantity: Mapped[int] = mapped_column(default=1)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("conflict_records.id")
    )


@pytest.fixture
async def database(tmp_path):
    db = DBConnection(
        f"sqlite+aiosqlite:///{tmp_path}/conflicts.db",
        1,
        0,
        5,
        1800,
        uow_factory=SQLiteUnitOfWork,
    )
    try:
        async with db.engine.begin() as connection:
            # DBConnection uses autocommit=False. SQLite only accepts this
            # pragma outside a transaction; restore the transaction afterward.
            await connection.execute(text("COMMIT"))
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.execute(text("BEGIN"))
            assert await connection.scalar(text("PRAGMA foreign_keys")) == 1
            await connection.run_sync(Base.metadata.create_all)
        async with db.uow() as current:
            async with current.transaction():
                current.session.add(Record(id=1, code="existing"))
        yield db
    finally:
        await db.dispose()


@pytest.mark.parametrize("phase", ["execute", "flush", "commit"])
async def test_real_unique_failure_rolls_back_and_unit_can_be_reused(
    database, phase
):
    class Service(Checks):
        entity = "Record"

        @handle_conflicts
        @transactional
        async def create(self):
            current = UnitOfWork.current()
            row = Record(id=2, code="existing")
            if phase == "execute":
                await current.execute(
                    insert(Record).values(id=2, code="existing")
                )
            else:
                current.session.add(row)
                if phase == "flush":
                    await current.flush()
                # Otherwise the transaction owner flushes during commit.

    async with database.uow() as current:
        with pytest.raises(ConflictException) as caught:
            await Service().create()
        assert caught.value.message == "Record already exists."
        assert isinstance(caught.value.__cause__, IntegrityError)
        assert not current.in_transaction
        async with current.transaction():
            current.session.add(Record(id=3, code="valid"))
    async with database.session_factory() as observer:
        assert list(
            await observer.scalars(select(Record.id).order_by(Record.id))
        ) == [1, 3]


async def test_manual_cleanup_and_undecorated_behavior(database):
    async with database.uow() as current:

        async def insert_duplicate():
            await current.execute(insert(Record).values(id=1, code="another"))

        for operation, exception in (
            (insert_duplicate, IntegrityError),
            (handle_conflicts(insert_duplicate), ConflictException),
        ):
            with pytest.raises(exception):
                await operation()
            assert current.in_transaction  # Decorator did not roll back.
            await current.rollback()


async def test_savepoint_cleanup_remains_owned_by_savepoint(database):
    async with database.uow() as current:

        @handle_conflicts
        async def optional_record():
            async with current.savepoint():
                await current.execute(
                    insert(Record).values(id=2, code="existing")
                )

        async with current.transaction():
            with pytest.raises(ConflictException):
                await optional_record()
            assert current.in_transaction
            current.session.add(Record(id=3, code="valid"))
    async with database.session_factory() as observer:
        assert list(
            await observer.scalars(select(Record.id).order_by(Record.id))
        ) == [1, 3]


@pytest.mark.parametrize(
    "changes", [{"quantity": -1}, {"code": None}, {"parent_id": 999}]
)
async def test_real_non_unique_constraints_stay_native(database, changes):
    @handle_conflicts
    @transactional
    async def operation():
        values = {"id": 2, "code": "new", **changes}
        await UnitOfWork.current().execute(insert(Record).values(**values))

    async with database.uow():
        with pytest.raises(IntegrityError):
            await operation()
