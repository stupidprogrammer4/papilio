"""Function execution in native Dishka request scopes, without SQL policy."""

import asyncio
import inspect
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
from typing import Any

from anyio import CancelScope
from dishka import AsyncContainer, Scope
from dishka.integrations.base import ContainerGetter, wrap_injection


@dataclass
class _Execution:
    request: AsyncContainer
    owner: asyncio.Task[Any] | None
    active: bool = True


_executions: ContextVar[tuple[_Execution, ...]] = ContextVar(
    "papilio_request_executions", default=()
)


def _has_source(request: AsyncContainer, source: AsyncContainer) -> bool:
    ancestor: AsyncContainer | None = request
    while ancestor is not None:
        if ancestor is source:
            return True
        ancestor = ancestor.parent_container
    return False


def _existing_request(source: AsyncContainer) -> AsyncContainer | None:
    for execution in reversed(_executions.get()):
        if not _has_source(execution.request, source):
            continue
        if source is execution.request and (
            not execution.active
            or execution.owner is not asyncio.current_task()
        ):
            raise RuntimeError(
                "Request scope belongs to another or closed task"
            )
        if execution.active and execution.owner is asyncio.current_task():
            return execution.request
    if source.scope is Scope.REQUEST:
        return source
    return None


@asynccontextmanager
async def _request_scope(
    source: AsyncContainer,
) -> AsyncIterator[AsyncContainer]:
    request = _existing_request(source)
    if request is not None:
        yield request
        return

    # Native scope construction/finalization owns all provider resources.
    scope = source(scope=Scope.REQUEST)
    request = await scope.__aenter__()
    try:
        yield request
    finally:
        # Match Papilio's tool adapters: finalize providers on cancellation.
        with CancelScope(shield=True):
            await scope.__aexit__(*sys.exc_info())


def request_scoped[**P, R](
    *, container_getter: ContainerGetter[AsyncContainer]
) -> Callable[
    [Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]
]:
    """Inject FromDishka arguments in a borrowed or owned request scope.

    The getter receives the call's positional and keyword arguments. Bind this
    adapter at an execution/composition boundary; business services keep their
    constructor-injected dependencies. Nested calls from the same task and
    source reuse their request. Independent tasks using the application
    container get independent requests. Never share a request across tasks.

    No application transaction is opened or committed by this adapter. Return
    materialized results; lazy iterators and live session-bound objects need a
    longer-lived owner. Async generators and sync callables are not supported.
    """

    def decorate(
        function: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        if not inspect.iscoroutinefunction(function):
            raise TypeError("@request_scoped requires an async function")

        current: ContextVar[AsyncContainer] = ContextVar(
            "papilio_injection_container"
        )
        injected = wrap_injection(
            func=function,
            container_getter=lambda args, kwargs: current.get(),
            is_async=True,
        )

        @wraps(injected)
        async def invoke(*args: P.args, **kwargs: P.kwargs) -> R:
            source = container_getter(args, kwargs)
            async with _request_scope(source) as request:
                execution = _Execution(request, asyncio.current_task())
                executions_token = _executions.set(
                    (*_executions.get(), execution)
                )
                injection_token = current.set(request)
                try:
                    result = await injected(*args, **kwargs)
                finally:
                    current.reset(injection_token)
                    execution.active = False
                    _executions.reset(executions_token)
            return result

        return invoke

    return decorate
