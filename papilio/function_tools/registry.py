"""Explicit application function tools, independent of model adapters."""

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

type ToolGuard = Callable[[Any, Mapping[str, Any]], Awaitable[bool]]


class ToolEffect(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True)
class FunctionTool:
    function: Callable[..., Awaitable[Any]]
    key: str
    name: str
    title: str
    description: str
    effect: ToolEffect
    authorize: ToolGuard
    approve: ToolGuard | None = None
    sequential: bool = True

    def __post_init__(self) -> None:
        if not inspect.iscoroutinefunction(self.function):
            raise TypeError("Function tools require an async function")
        if not all(
            value.strip()
            for value in (self.key, self.name, self.title, self.description)
        ):
            raise ValueError("Function tool metadata must be nonempty")
        if not isinstance(self.effect, ToolEffect):
            raise TypeError("Function tools require an explicit ToolEffect")
        if not callable(self.authorize):
            raise TypeError("Function tools require an authorization hook")
        if self.effect == ToolEffect.WRITE and not callable(self.approve):
            raise TypeError("Write function tools require an approval hook")


class FunctionTools:
    """Collect explicitly declared tools for application discovery."""

    def __init__(self) -> None:
        self._tools: list[FunctionTool] = []

    @property
    def tools(self) -> tuple[FunctionTool, ...]:
        return tuple(self._tools)

    def tool[**P, R](
        self,
        *,
        key: str,
        name: str,
        title: str,
        description: str,
        effect: ToolEffect,
        authorize: ToolGuard,
        approve: ToolGuard | None = None,
        sequential: bool = True,
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        def register(
            function: Callable[P, Awaitable[R]],
        ) -> Callable[P, Awaitable[R]]:
            self._tools.append(
                FunctionTool(
                    function,
                    key,
                    name,
                    title,
                    description,
                    effect,
                    authorize,
                    approve,
                    sequential,
                )
            )
            return function

        return register
