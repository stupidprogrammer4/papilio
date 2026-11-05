"""Controlled configuration failures never expose private coefficients."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import ValidationError

from papilio.core.encryption import get_id_encryption_settings

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def clear_settings() -> Iterator[None]:
    get_id_encryption_settings.cache_clear()
    yield
    get_id_encryption_settings.cache_clear()


@pytest.mark.parametrize(
    "params",
    [
        {"mod": "9000", "coff": 7},
        {"mod": True, "coff": 7},
        {"mod": 9000, "coff": 7.0},
        {"mod": 9000},
        {"mod": 9000, "coff": 7, "unknown": 1},
        {"mod": 9000, "coff": 7, "entity": 42},
    ],
)
def test_file_types_are_validated_before_constructing_codecs(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, object]
) -> None:
    payload = json.dumps({"example/items": params}).encode()
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValidationError):
        get_id_encryption_settings()


@pytest.mark.parametrize(
    "payload", [b"[]", b"not json", b'{"example/items":null}']
)
def test_malformed_root_is_rejected(
    monkeypatch: pytest.MonkeyPatch, payload: bytes
) -> None:
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValidationError):
        get_id_encryption_settings()


@pytest.mark.parametrize(
    "params",
    [
        {"mod": 1, "coff": 7},
        {"mod": 9000, "coff": 9000},
        {"mod": 9000, "coff": 3},
        {"mod": 9000, "coff": 7, "offset": -1},
    ],
)
def test_native_parameter_checks_propagate(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, object]
) -> None:
    payload = json.dumps({"example/items": params}).encode()
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValueError):
        get_id_encryption_settings()


def test_duplicate_entity_bindings_fail_instead_of_selecting_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.dumps(
        {
            "example/first": {"mod": 97, "coff": 7, "entity": "Item"},
            "example/second": {"mod": 101, "coff": 11, "entity": "Item"},
        }
    ).encode()
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValueError, match="Duplicate public-ID entity"):
        get_id_encryption_settings()


def test_configuration_errors_hide_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'{"example/items":{"mod":97,"coff":"private-coefficient"}}'
    monkeypatch.setattr(Path, "read_bytes", lambda self: payload)
    with pytest.raises(ValidationError) as error:
        get_id_encryption_settings()
    assert "private-coefficient" not in str(error.value)
