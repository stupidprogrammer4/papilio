"""Optional native MCP adapter over the same function tool executor."""

import inspect
from collections.abc import Callable
from functools import wraps
from typing import Any

try:
    from mcp.server import MCPServer
    from mcp.server.context import (
        CallNext,
        HandlerResult,
        ServerRequestContext,
    )
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.shared.exceptions import MCPError
except ModuleNotFoundError as exc:
    if exc.name == "mcp":
        raise ImportError("MCP function tools require papilio[mcp].") from exc
    raise

from mcp_types import ToolAnnotations

from papilio.errors.base import APPException
from papilio.function_tools.execution import (
    BoundFunctionTool,
    FunctionToolExecutor,
)
from papilio.function_tools.registry import ToolEffect


def _invoke(
    bound: BoundFunctionTool, current_context: Callable[[], Any]
) -> Callable[..., Any]:
    @wraps(bound.function)
    async def invoke(**arguments: Any) -> Any:
        try:
            result = await bound.invoke(arguments, context=current_context())
        except APPException as error:
            raise ToolError(error.as_schema().model_dump_json()) from error
        return result

    setattr(
        invoke,
        "__signature__",
        bound.signature.replace(return_annotation=bound.output_type),
    )
    return invoke


def build_server(
    executor: FunctionToolExecutor,
    *,
    current_context: Callable[[], Any],
    name: str,
) -> MCPServer:
    """Expose selected tools with application-owned identity and discovery."""
    server = MCPServer(name)
    allowed = {
        bound.definition.name: bound.signature.parameters.keys()
        for bound in executor.tools
    }

    async def validate_names(
        ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if ctx.method == "tools/call":
            params = ctx.params or {}
            arguments = params.get("arguments", {})
            tool_name = params.get("name")
            names = (
                allowed.get(tool_name) if isinstance(tool_name, str) else None
            )
            if names is not None and isinstance(arguments, dict):
                if arguments.keys() - names:
                    raise MCPError(
                        code=-32602,
                        message="Unexpected function tool arguments",
                    )
        result = await call_next(ctx)
        return result

    server.middleware.append(validate_names)
    for bound in executor.tools:
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in bound.signature.parameters.values()
        ):
            raise TypeError("MCP function tools require named parameters")
        definition = bound.definition
        server.add_tool(
            _invoke(bound, current_context),
            name=definition.name,
            title=definition.title,
            description=definition.description,
            annotations=ToolAnnotations(
                read_only_hint=definition.effect == ToolEffect.READ,
                destructive_hint=definition.effect == ToolEffect.WRITE,
            ),
            meta={"key": definition.key, "effect": definition.effect.value},
        )
    return server
