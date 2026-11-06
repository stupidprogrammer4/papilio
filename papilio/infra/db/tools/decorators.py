"""Decorators for application database operations."""

import inspect
from collections.abc import Awaitable, Callable
from functools import wraps
from types import CoroutineType
from typing import Any, cast

from papilio.infra.db.transaction import transaction


def transactional[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, CoroutineType[Any, Any, R]]:
    if not inspect.iscoroutinefunction(function):
        raise TypeError("@transactional requires an async function")

    @wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        async with transaction():
            return await function(*args, **kwargs)

    return cast(Callable[P, CoroutineType[Any, Any, R]], wrapped)
