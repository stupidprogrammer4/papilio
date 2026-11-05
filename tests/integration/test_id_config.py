"""Read isolated real configuration files without database infrastructure."""

import json
from collections.abc import Iterator, MutableMapping
from pathlib import Path
from typing import cast

import pytest

from papilio.core.encryption import get_id_encryption_settings

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def clear_settings() -> Iterator[None]:
    get_id_encryption_settings.cache_clear()
    yield
    get_id_encryption_settings.cache_clear()


def test_file_loading_is_cached_and_entities_are_explicit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "encryption.json"
    path.write_text(
        json.dumps(
            {
                "example/items": {"mod": 101, "coff": 7, "entity": "Item"},
                "example/other": {"mod": 97, "coff": 11, "offset": 500},
            }
        )
    )
    settings = get_id_encryption_settings(path)
    assert settings.resources["example/items"] is settings.entities["Item"]
    assert tuple(settings.entities) == ("Item",)
    encoded = settings.resources["example/items"].encode(42)
    path.write_text('{"example/items":{"mod":101,"coff":11}}')
    assert get_id_encryption_settings(path) is settings
    assert settings.resources["example/items"].encode(42) == encoded
    assert "7" not in repr(settings.resources["example/items"])
    with pytest.raises(TypeError):
        mutable = cast(MutableMapping[str, object], settings.resources)
        mutable["other"] = settings.resources["example/items"]


def test_environment_selection_and_missing_file_have_no_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "selected.json"
    monkeypatch.setenv("PAPILIO_ENCRYPTION", str(path))
    (tmp_path / "encryption.sample.json").write_text("{}")
    with pytest.raises(FileNotFoundError):
        get_id_encryption_settings()
    path.write_text('{"example/items":{"mod":101,"coff":11}}')
    assert (
        get_id_encryption_settings().resources["example/items"].encode(42)
        == 58
    )
