from dishka import FromDishka

from papilio.mcp.router import MCPRouter
from <<PKG>>.<<M>>.domain.entities import <<P>>Model
from <<PKG>>.<<M>>.interfaces import I<<P>>Service

tools = MCPRouter()


@tools.tool(name="<<TOOL_PREFIX>>_get")
async def get_by_id(
    id: int, service: FromDishka[I<<P>>Service]
) -> <<P>>Model:
    """Get a <<S>> by its identifier."""
    return await service.get_by_id(id)
