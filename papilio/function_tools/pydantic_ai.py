"""Optional native Pydantic AI function toolset adapter."""

from functools import partial
from typing import Any

from anyio import to_thread

try:
    from pydantic_ai import RunContext, Tool, ToolFailed
    from pydantic_ai.toolsets import FunctionToolset
except ModuleNotFoundError as exc:
    if exc.name == "pydantic_ai":
        raise ImportError(
            "Pydantic AI tools require papilio[function-tools-pydantic-ai]."
        ) from exc
    raise

from papilio.function_tools.execution import (
    BoundFunctionTool,
    FunctionToolExecutor,
)
from papilio.function_tools.registry import ToolEffect


def _model_tool(bound: BoundFunctionTool) -> Tool[Any]:
    definition = bound.definition

    async def validate(ctx: RunContext[Any], **arguments: Any) -> None:
        try:
            await to_thread.run_sync(partial(bound.validate_input, arguments))
        except ValueError:
            raise ToolFailed(
                "Invalid tool arguments; use the declared input schema."
            ) from None

    async def invoke(ctx: RunContext[Any], **arguments: Any) -> Any:
        result = await bound.invoke(arguments, context=ctx.deps)
        return result

    tool = Tool.from_schema(
        invoke,
        name=definition.name,
        description=definition.description,
        json_schema=bound.input_schema,
        takes_ctx=True,
        sequential=definition.sequential,
        args_validator=validate,
    )
    tool.requires_approval = definition.effect == ToolEffect.WRITE
    tool.metadata = {
        "key": definition.key,
        "title": definition.title,
        "effect": definition.effect.value,
    }
    return tool


def build_toolset(executor: FunctionToolExecutor) -> FunctionToolset[Any]:
    """Adapt selected tools with authoritative application guards."""
    return FunctionToolset(
        [_model_tool(tool) for tool in executor.tools],
        id="papilio_function_tools",
        max_retries=0,
    )
