import re
from typing import Any, Unpack

from sqlalchemy import BigInteger, Index
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from papilio.infra.db.schema.fields import FieldOptions, _field

from .base import DatabaseDialect


class PGDialect(DatabaseDialect):
    name = "postgresql"

    def unique_values(self, error):
        cause = getattr(error.orig, "__cause__", None) or error.orig
        code = getattr(cause, "sqlstate", None) or getattr(
            cause, "pgcode", None
        )
        if code != "23505":
            return None
        detail = getattr(cause, "detail", None)
        if detail is None:
            detail = getattr(
                getattr(cause, "diag", None), "message_detail", ""
            )
        found = re.fullmatch(
            r"Key \(([^()]*)\)=\((.*)\) already exists\.",
            detail or "",
            re.DOTALL,
        )
        if found is None:
            return {}
        names = found.group(1).split(", ")
        # Diagnostic text is not an escaped serialization format. Restrict
        # column names and reject ambiguous composite values rather than
        # truncating/mispairing them. Single values may contain commas.
        if any(
            re.fullmatch(r"[A-Za-z_][A-Za-z_0-9$]*", name) is None
            for name in names
        ):
            return {}
        values = (
            [found.group(2)] if len(names) == 1 else found.group(2).split(", ")
        )
        if len(names) != len(values) or len(set(names)) != len(names):
            return {}
        return dict(zip(names, values, strict=True))


async def reset_schema(connection):
    from sqlalchemy import text

    await connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    await connection.execute(text("CREATE SCHEMA public"))


async def truncate_tables(session, tables):
    from sqlalchemy import text

    preparer = session.get_bind().dialect.identifier_preparer
    names = ", ".join(preparer.format_table(table) for table in tables)
    await session.execute(
        text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")
    )


def JSONBField(
    *,
    none_as_null: bool = False,
    **options: Unpack[FieldOptions],
) -> Any:
    return _field(JSONB(none_as_null=none_as_null), **options)


def ArrayField(
    item_type: Any = BigInteger,
    *,
    dimensions: int | None = None,
    gin_index: str | None = None,
    **options: Unpack[FieldOptions],
) -> Any:
    """Declare an array and optionally its column-attached GIN index."""
    field = _field(ARRAY(item_type, dimensions=dimensions), **options)
    if gin_index:
        from sqlmodel import Field
        from sqlmodel.main import get_column_from_field

        column = get_column_from_field(field)
        Index(gin_index, column, postgresql_using="gin")
        return Field(
            default=field.default,
            default_factory=field.default_factory,
            alias=field.alias,
            description=field.description,
            sa_column=column,
        )
    return field
