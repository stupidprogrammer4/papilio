from collections.abc import Mapping
from typing import Any

from dishka import FromDishka

from papilio.function_tools.registry import FunctionTools, ToolEffect
from <<PKG>>.<<M>>.app.results import <<P>>Out
from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.interfaces import I<<P>>Service

tools = FunctionTools()


async def authorize_run(
    context: Any, arguments: Mapping[str, Any]
) -> bool:
    """Implement the application's actor and record access policy."""
    raise NotImplementedError("Configure Function Tool authorization")


async def approve_run(
    context: Any, arguments: Mapping[str, Any]
) -> bool:
    """Check the application's approval for these exact arguments."""
    raise NotImplementedError("Configure Function Tool approval")


@tools.tool(
    key="<<M>>.run",
    name="<<TOOL_PREFIX>>_run",
    title="Run <<S>>",
    description="Run the <<S>> service after authorization and approval.",
    effect=ToolEffect.WRITE,
    authorize=authorize_run,
    approve=approve_run,
)
async def run(
    data: <<P>>Input, service: FromDishka[I<<P>>Service]
) -> <<P>>Out:
    result = await service.run(data)
    return result
