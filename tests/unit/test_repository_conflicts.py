"""Driver-specific unique-error decoding remains an explicit dialect tool."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from papilio.infra.db.dialects.postgresql import PGDialect


@pytest.mark.parametrize(
    "detail,expected",
    [
        ("Key (code)=(abc) already exists.", {"code": "abc"}),
        (
            "Key (code, tenant_id)=(abc, 3) already exists.",
            {"code": "abc", "tenant_id": "3"},
        ),
        ("unknown localized detail", {}),
        (
            "Key (code)=(hello, world) already exists.",
            {"code": "hello, world"},
        ),
        ("Key (code)=() already exists.", {"code": ""}),
        ("Key (code)=( padded ) already exists.", {"code": " padded "}),
        ("Key (code, tenant_id)=(hello, world, 3) already exists.", {}),
        ('Key ("a, b")=(value) already exists.', {}),
        ("Key (code, code)=(a, b) already exists.", {}),
    ],
)
def test_unique_violation_details(detail, expected):
    cause = SimpleNamespace(sqlstate="23505", detail=detail)
    error = IntegrityError("stmt", {}, SimpleNamespace(__cause__=cause))
    assert PGDialect().unique_values(error) == expected


@pytest.mark.parametrize("sqlstate", ["23503", "23514", None])
def test_other_integrity_errors_are_not_unique_conflicts(sqlstate):
    cause = SimpleNamespace(sqlstate=sqlstate, detail="not a unique error")
    error = IntegrityError("stmt", {}, SimpleNamespace(__cause__=cause))
    assert PGDialect().unique_values(error) is None


def test_psycopg2_code_and_diagnostic_detail():
    original = SimpleNamespace(
        pgcode="23505",
        diag=SimpleNamespace(
            message_detail="Key (code)=(abc) already exists."
        ),
    )
    assert PGDialect().unique_values(IntegrityError("stmt", {}, original)) == {
        "code": "abc"
    }


@pytest.mark.parametrize(
    "backend,original,expected",
    [
        ("mysql", Exception(1062, "Duplicate"), {}),
        ("mysql", Exception(1452, "Foreign key"), None),
        ("mariadb", Exception(1062, "Duplicate"), {}),
        ("mariadb", Exception(1048, "Not null"), None),
        ("sqlite", SimpleNamespace(sqlite_errorcode=1555), {}),
        ("sqlite", SimpleNamespace(sqlite_errorcode=2067), {}),
        ("sqlite", SimpleNamespace(sqlite_errorcode=787), None),
        ("sqlite", SimpleNamespace(sqlite_errorcode=275), None),
        ("mssql", Exception("23000", "duplicate (2601)"), {}),
        ("mssql", Exception("23000", "duplicate (2627)"), {}),
        ("mssql", Exception("23000", "foreign key (547)"), None),
        ("oracle", Exception(SimpleNamespace(code=1)), {}),
        ("oracle", Exception(SimpleNamespace(code=2291)), None),
    ],
)
def test_native_unique_classification(backend, original, expected):
    from papilio.infra.db.dialects import get_dialect

    error = IntegrityError("stmt", {}, original)
    assert get_dialect(backend).unique_values(error) == expected
