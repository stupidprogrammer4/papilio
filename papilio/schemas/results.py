from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, Sequence, TypeVar


@dataclass(frozen=True, slots=True)
class PatchResult[T, P]:
    """A result and its applied patch, without validation or conversion."""

    affected: int | None
    value: T
    patch: P


@dataclass(frozen=True, slots=True)
class DeleteResult[T]:
    """A deletion result, without validation or conversion."""

    affected: int | None
    value: T


@dataclass(frozen=True, slots=True)
class BatchResultType[T, E]:
    """A clean, named return value for batch lookups — a typed stand-in for a
    bare tuple, no validation. Carries the resolved ``items``, the per-item
    ``errors`` for the ones that failed, and the set of ids that resolved."""

    items: Sequence[T]
    errors: Sequence[E]
    item_ids: set[int] = field(default_factory=set)


# covariant: a read-only page of table rows is a page of the model they
# extend, and PEP 695 syntax infers invariance for a dataclass field
TItem = TypeVar("TItem", covariant=True)


@dataclass(frozen=True, slots=True)
class PagedType(Generic[TItem]):
    items: Sequence[TItem]
    total_items: int
