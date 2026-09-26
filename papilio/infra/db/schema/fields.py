"""Convenient field declarations with explicit model and SQL defaults."""

import enum
from collections.abc import Callable, Mapping
from typing import Any, TypedDict, Unpack

from pydantic_core import PydanticUndefined
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import Enum as SAEnum
from sqlmodel import Field


class FieldOptions(TypedDict, total=False):
    default: Any
    default_factory: Callable[[], Any]
    nullable: bool
    index: bool
    unique: bool
    primary_key: bool
    db_column: str
    comment: str
    alias: str
    description: str
    server_default: Any
    onupdate: Any
    server_onupdate: Any
    sa_column_kwargs: Mapping[str, Any]


def _field(
    type_: Any,
    *column_args: Any,
    default: Any = PydanticUndefined,
    default_factory: Callable[[], Any] | None = None,
    nullable: bool = False,
    index: bool = False,
    unique: bool = False,
    primary_key: bool = False,
    db_column: str | None = None,
    comment: str | None = None,
    alias: str | None = None,
    description: str | None = None,
    server_default: Any = None,
    onupdate: Any = None,
    server_onupdate: Any = None,
    sa_column_kwargs: Mapping[str, Any] | None = None,
) -> Any:
    """Forward declared options; strings remain SQLAlchemy string defaults.

    default/default_factory belong to the model. SQLModel may also use them
    for inserts, following its native behavior. SQL expressions are supplied
    explicitly, e.g. server_default=text("CURRENT_TIMESTAMP"). Advanced
    sa_column_kwargs override the corresponding SQL options below.
    """
    return Field(
        default=default,
        default_factory=default_factory,
        nullable=nullable,
        index=index,
        unique=unique,
        primary_key=primary_key,
        alias=alias,
        description=description,
        sa_type=type_,
        sa_column_args=column_args,
        sa_column_kwargs={
            "name": db_column,
            "comment": comment,
            "server_default": server_default,
            "onupdate": onupdate,
            "server_onupdate": server_onupdate,
            **(sa_column_kwargs or {}),
        },
    )


def IDField(
    *, autoincrement: bool = True, db_column: str | None = None
) -> Any:
    return _field(
        BigInteger().with_variant(Integer, "sqlite"),
        *((Identity(),) if autoincrement else ()),
        default=None,
        primary_key=True,
        db_column=db_column,
        sa_column_kwargs={"autoincrement": autoincrement},
    )


def SmallIntField(**options: Unpack[FieldOptions]) -> Any:
    return _field(SmallInteger, **options)


def IntField(**options: Unpack[FieldOptions]) -> Any:
    return _field(Integer, **options)


def BigIntField(**options: Unpack[FieldOptions]) -> Any:
    return _field(BigInteger, **options)


def BoolField(**options: Unpack[FieldOptions]) -> Any:
    return _field(Boolean, **options)


def FloatField(**options: Unpack[FieldOptions]) -> Any:
    return _field(Float, **options)


def NumericField(
    precision: int | None = None,
    scale: int | None = None,
    **options: Unpack[FieldOptions],
) -> Any:
    return _field(Numeric(precision, scale), **options)


def CharField(length: int, **options: Unpack[FieldOptions]) -> Any:
    return _field(String(length), **options)


def TextField(**options: Unpack[FieldOptions]) -> Any:
    return _field(Text, **options)


def DateField(**options: Unpack[FieldOptions]) -> Any:
    return _field(Date, **options)


def TimeField(**options: Unpack[FieldOptions]) -> Any:
    """Store a local clock time without a date or timezone."""
    return _field(Time(timezone=False), **options)


def TimestampField(**options: Unpack[FieldOptions]) -> Any:
    return _field(DateTime(timezone=True), **options)


def VersionField(**options: Unpack[FieldOptions]) -> Any:
    """A version column; defaults and advancement are explicit options."""
    return _field(BigInteger, **options)


def JSONField(
    *,
    none_as_null: bool = False,
    **options: Unpack[FieldOptions],
) -> Any:
    from papilio.infra.db.dialects.oracle import OracleJSON

    return _field(
        JSON(none_as_null=none_as_null)
        .with_variant(JSONB(none_as_null=none_as_null), "postgresql")
        .with_variant(OracleJSON(none_as_null=none_as_null), "oracle"),
        **options,
    )


def EnumField(
    enum_cls: type[enum.Enum],
    *,
    native_enum: bool = True,
    values_callable: Callable[[type[enum.Enum]], list[str]] | None = None,
    length: int | None = None,
    **options: Unpack[FieldOptions],
) -> Any:
    """Map members to native enums or text with SQLAlchemy defaults."""
    enum_options = {"length": length} if length is not None else {}
    return _field(
        SAEnum(
            enum_cls,
            native_enum=native_enum,
            values_callable=values_callable,
            **enum_options,
        ),
        **options,
    )


def ComputedField(
    expression: str,
    type_: Any = Boolean,
    *,
    persisted: bool = True,
    **options: Unpack[FieldOptions],
) -> Any:
    return _field(type_, Computed(expression, persisted=persisted), **options)


def ForeignKeyField(
    target: str,
    *,
    ondelete: str | None = None,
    **options: Unpack[FieldOptions],
) -> Any:
    return _field(BigInteger, ForeignKey(target, ondelete=ondelete), **options)
