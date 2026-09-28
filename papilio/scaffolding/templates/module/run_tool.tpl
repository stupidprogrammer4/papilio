from dishka import FromDishka

from papilio.mcp.router import MCPRouter
from <<PKG>>.<<M>>.app.results import <<P>>Out
from <<PKG>>.<<M>>.domain.dtos import <<P>>Input
from <<PKG>>.<<M>>.interfaces import I<<P>>Service

tools = MCPRouter()


@tools.tool(name="<<TOOL_PREFIX>>_run")
async def run(
    data: <<P>>Input, service: FromDishka[I<<P>>Service]
) -> <<P>>Out:
    """Run the <<S>> service."""
    return await service.run(data)
