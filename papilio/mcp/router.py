"""Application-owned MCP tool definitions, independent of server lifetime."""

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    function: Callable[..., Awaitable[Any]]
    name: str
    description: str | None


class MCPRouter:
    """Collect explicitly exposed async tools for discovery or registration."""

    def __init__(self) -> None:
        self._tools: list[ToolDefinition] = []

    @property
    def tools(self) -> tuple[ToolDefinition, ...]:
        return tuple(self._tools)

    def tool[**P, R](
        self, *, name: str | None = None, description: str | None = None
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Register an async function; FromDishka arguments are injected."""

        def register(
            function: Callable[P, Awaitable[R]],
        ) -> Callable[P, Awaitable[R]]:
            if not inspect.iscoroutinefunction(function):
                raise TypeError("MCP tools require an async function")
            tool_name = name or function.__name__
            self._tools.append(
                ToolDefinition(function, tool_name, description)
            )
            return function

        return register
