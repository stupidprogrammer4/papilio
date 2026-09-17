"""HTTP query models and validated integer pairs."""

from collections.abc import Sequence
from typing import Annotated

from pydantic import BeforeValidator, ConfigDict

from papilio.schemas.inputs import BaseDTO


def _parse_pair(value: object) -> tuple[int, int]:
    """Parse a decimal `<key>:<value>` string during input validation."""
    message = "each pick reads as <key>:<value>"
    if not isinstance(value, str):
        raise ValueError(message)
    key, separator, picked = value.partition(":")
    if not separator or not key.isdecimal() or not picked.isdecimal():
        raise ValueError(message)
    try:
        return int(key), int(picked)
    except ValueError:
        raise ValueError(message) from None


QueryPair = Annotated[
    tuple[int, int],
    BeforeValidator(_parse_pair, json_schema_input_type=str),
]


def pairs_folded(value: Sequence[tuple[int, int]]) -> dict[int, list[int]]:
    """Group validated integer pairs, preserving value order and duplicates."""
    folded: dict[int, list[int]] = {}
    for key, picked in value:
        folded.setdefault(key, []).append(picked)
    return folded


class BaseQuery(BaseDTO):
    """Query DTO with explicit field aliases and field-name population."""

    model_config = ConfigDict(populate_by_name=True)
