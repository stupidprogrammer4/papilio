"""Bind discovered tools to the application's Dishka container."""

import inspect
import sys
from collections.abc import Awaitable, Callable, Sequence
from contextvars import ContextVar
from functools import wraps
from typing import Any, get_type_hints

from anyio import CancelScope
from dishka import AsyncContainer, Scope
from dishka.integrations.base import wrap_injection

try:
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ModuleNotFoundError as exc:
    if exc.name == "mcp":
        raise ImportError(
            "MCP support requires papilio[mcp]. Install that extra first."
        ) from exc
    raise

from papilio.errors.base import APPException
from papilio.mcp.router import MCPRouter, ToolDefinition


def _bind(
    tool: ToolDefinition, container: AsyncContainer
) -> Callable[..., Awaitable[Any]]:
    current: ContextVar[AsyncContainer] = ContextVar("mcp_tool_container")
    injected = wrap_injection(
        func=tool.function,
        container_getter=lambda args, kwargs: current.get(),
        is_async=True,
    )

    @wraps(injected)
    async def invoke(*args: Any, **kwargs: Any) -> Any:
        scope = container(scope=Scope.REQUEST)
        child = await scope.__aenter__()
        token = current.set(child)
        try:
            try:
                return await injected(*args, **kwargs)
            finally:
                # A cancelled call must still finalize async providers.
                with CancelScope(shield=True):
                    await scope.__aexit__(*sys.exc_info())
        except APPException as exc:
            raise ToolError(exc.as_schema().model_dump_json()) from exc
        finally:
            current.reset(token)

    # Dishka resolves input hints but preserves a postponed return annotation.
    signature = inspect.signature(injected, eval_str=True)
    setattr(
        invoke,
        "__signature__",
        signature.replace(
            return_annotation=get_type_hints(
                tool.function, include_extras=True
            ).get("return", signature.return_annotation),
        ),
    )
    return invoke


def build_server(
    routers: Sequence[MCPRouter], container: AsyncContainer, *, name: str
) -> MCPServer:
    """Build an app-local server without taking ownership of its container."""
    server = MCPServer(name)
    names: set[str] = set()
    for router in dict.fromkeys(routers):
        for tool in router.tools:
            if tool.name in names:
                raise ValueError(f"Duplicate MCP tool name: {tool.name!r}")
            names.add(tool.name)
            server.add_tool(
                _bind(tool, container),
                name=tool.name,
                description=tool.description,
            )
    return server
