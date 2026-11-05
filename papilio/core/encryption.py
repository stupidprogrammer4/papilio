"""Explicit public-ID configuration, independent of application resources."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from papilio.tools.ids import IDEncryption


class IDEncryptionConfig(BaseModel):
    """Untrusted file parameters; IDEncryption owns numeric compatibility."""

    model_config = ConfigDict(
        strict=True, extra="forbid", hide_input_in_errors=True
    )

    mod: int
    coff: int = Field(repr=False)
    offset: int = 0
    entity: str | None = None


@dataclass(frozen=True, slots=True)
class IDEncryptionSettings:
    """Materialized read-only codecs by resource and opted-in error entity."""

    resources: Mapping[str, IDEncryption]
    entities: Mapping[str, IDEncryption]


@lru_cache(maxsize=1)
def get_id_encryption_settings(
    path: Path | None = None,
) -> IDEncryptionSettings:
    """Load explicitly configured public-ID codecs once during initialization.

    Args:
        path: Explicit JSON file. Otherwise PAPILIO_ENCRYPTION selects it,
            defaulting to encryption.json in the working directory.

    Returns:
        Immutable mappings by resource key and optional unique error entity.
        Loading a resource does not transform any field automatically.

    Raises:
        OSError: The selected file cannot be read; no fallback is attempted.
        pydantic.ValidationError: JSON or parameter types are invalid.
        ValueError: Codec parameters or duplicate entity bindings are invalid.
    """
    source = path or Path(
        os.environ.get("PAPILIO_ENCRYPTION", "encryption.json")
    )
    configs = TypeAdapter(
        dict[str, IDEncryptionConfig],
        config=ConfigDict(hide_input_in_errors=True),
    ).validate_json(source.read_bytes())
    resources: dict[str, IDEncryption] = {}
    entities: dict[str, IDEncryption] = {}
    for resource, config in configs.items():
        codec = IDEncryption(config.mod, config.coff, config.offset)
        resources[resource] = codec
        if config.entity is not None:
            if config.entity in entities:
                raise ValueError(
                    f"Duplicate public-ID entity: {config.entity}"
                )
            entities[config.entity] = codec
    return IDEncryptionSettings(
        resources=MappingProxyType(resources),
        entities=MappingProxyType(entities),
    )
