"""Opt-in translation of native unique violations at an async call boundary."""

import inspect
from collections.abc import Awaitable, Callable, Coroutine
from functools import wraps
from typing import Any, overload

from sqlalchemy.exc import IntegrityError

from papilio.errors.exceptions import ConflictException
from papilio.infra.db.dialects import get_dialect
from papilio.infra.db.uow import UnitOfWork
from papilio.tools.checks import Checks


@overload
def handle_conflicts[**P, R](
    function: Callable[P, Awaitable[R]],
    *,
    entity: str | type | None = None,
    message: str | None = None,
    message_code: str | None = None,
) -> Callable[P, Coroutine[Any, Any, R]]: ...


@overload
def handle_conflicts[**P, R](
    function: None = None,
    *,
    entity: str | type | None = None,
    message: str | None = None,
    message_code: str | None = None,
) -> Callable[
    [Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]
]: ...


def handle_conflicts[**P, R](
    function: Callable[P, Awaitable[R]] | None = None,
    *,
    entity: str | type | None = None,
    message: str | None = None,
    message_code: str | None = None,
) -> (
    Callable[P, Coroutine[Any, Any, R]]
    | Callable[
        [Callable[P, Awaitable[R]]], Callable[P, Coroutine[Any, Any, R]]
    ]
):
    """Translate unique/primary-key violations using the current open UoW.

    Use bare or with optional entity/message/code overrides. Entity defaults
    to a bound Checks instance's entity, then generic record wording. Only
    None requests a default; the default message code is "conflict".

    One decorated call belongs to the UoW/backend active at entry. Put this
    outside @transactional to include its commit errors. This decorator never
    commits, rolls back, retries, or opens a unit. Errors after the call
    returns are outside its scope. Async generators and sync functions
    are unsupported.
    """

    def decorate(
        operation: Callable[P, Awaitable[R]],
    ) -> Callable[P, Coroutine[Any, Any, R]]:
        if not inspect.iscoroutinefunction(operation):
            raise TypeError("@handle_conflicts requires an async function")
        first = next(
            iter(inspect.signature(operation).parameters.values()), None
        )
        receiver_name = (
            first.name
            if first is not None
            and first.kind
            in (first.POSITIONAL_ONLY, first.POSITIONAL_OR_KEYWORD)
            else None
        )

        @wraps(operation)
        async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            unit = UnitOfWork.current()
            if unit is None:
                raise RuntimeError(
                    "handle_conflicts requires an open UnitOfWork"
                )
            dialect = get_dialect(unit.connection.backend)
            try:
                return await operation(*args, **kwargs)
            except IntegrityError as error:
                values = dialect.unique_values(error)
                if values is None:
                    raise
                text = message
                if text is None:
                    name = (
                        entity.__name__ if isinstance(entity, type) else entity
                    )
                    if name is None and receiver_name is not None:
                        receiver = (
                            args[0] if args else kwargs.get(receiver_name)
                        )
                        if isinstance(receiver, Checks):
                            # A free function or staticmethod may take a Checks
                            # object as data; neither has a bound receiver.
                            # Include overridden base methods called via super.
                            for owner in type(receiver).__mro__:
                                member = vars(owner).get(operation.__name__)
                                if inspect.isfunction(member) and (
                                    inspect.unwrap(member)
                                    is inspect.unwrap(operation)
                                ):
                                    label = getattr(receiver, "entity", None)
                                    if isinstance(label, str):
                                        name = label
                                    break
                    if name is None:
                        text = "A record with these values already exists."
                    elif values:
                        fields = ", ".join(values)
                        text = f"{name} already exists with the same {fields}."
                    else:
                        text = f"{name} already exists."
                raise ConflictException(
                    message=text,
                    message_code=(
                        "conflict" if message_code is None else message_code
                    ),
                    unique_dict=values,
                ) from error

        return wrapped

    return decorate if function is None else decorate(function)
