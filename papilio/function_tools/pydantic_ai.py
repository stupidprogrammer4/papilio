"""Optional native Pydantic AI function toolset adapter."""

from functools import partial
from typing import Any, get_args

from anyio import to_thread
from pydantic import ValidationError
from pydantic_core.core_schema import ErrorType

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


def _declared_fields(schema: Any) -> set[str]:
    if isinstance(schema, dict):
        return set(schema.get("properties", {})).union(
            *(_declared_fields(value) for value in schema.values())
        )
    if isinstance(schema, list):
        return set().union(*(_declared_fields(value) for value in schema))
    return set()


def _model_tool(bound: BoundFunctionTool) -> Tool[Any]:
    definition = bound.definition
    fields = _declared_fields(bound.input_schema)
    error_types = frozenset(get_args(ErrorType))

    async def validate(ctx: RunContext[Any], **arguments: Any) -> None:
        try:
            await to_thread.run_sync(partial(bound.validate_input, arguments))
        except ValidationError as error:
            details = []
            for item in error.errors(
                include_input=False, include_context=False, include_url=False
            )[:3]:
                location = ".".join(
                    [part for part in item["loc"] if part in fields][:4]
                )
                kind = item["type"]
                if kind not in error_types:
                    kind = "validation_error"
                details.append(f"{location or 'arguments'}: {kind}")
            raise ToolFailed(
                ("Invalid tool arguments: " + "; ".join(details))[:512]
            ) from None
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
