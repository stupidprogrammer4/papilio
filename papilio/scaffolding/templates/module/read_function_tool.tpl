from collections.abc import Mapping
from typing import Any

from dishka import FromDishka

from papilio.function_tools.registry import FunctionTools, ToolEffect
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.interfaces import I<<P>>Service

tools = FunctionTools()


async def authorize_read(
    context: Any, arguments: Mapping[str, Any]
) -> bool:
    """Implement the application's actor and record access policy."""
    raise NotImplementedError("Configure Function Tool authorization")


@tools.tool(
    key="<<M>>.get",
    name="<<TOOL_PREFIX>>_get",
    title="Get <<S>>",
    description="Read a <<S>> by its identifier.",
    effect=ToolEffect.READ,
    authorize=authorize_read,
)
async def get_by_id(
    id: int, service: FromDishka[I<<P>>Service]
) -> <<P>>Model:
    result = await service.get_by_id(id)
    return result
