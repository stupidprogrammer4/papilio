"""Build an independent MCP application without loading HTTP routers."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

from anyio import CancelScope
from dishka import AsyncContainer, Provider, make_async_container
from starlette.applications import Starlette
from starlette.types import Lifespan

from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import Settings, get_settings
from papilio.core.logger import logger
from papilio.mcp.server import build_server
from papilio.providers.base import CoreProvider

if TYPE_CHECKING:
    from mcp.server import MCPServer


def create_app(
    settings: Settings | None = None,
    *,
    providers: Sequence[Provider] = (),
    server_factory: Callable[[AsyncContainer], MCPServer] | None = None,
    http_options: Mapping[str, Any] | None = None,
    lifespan: Lifespan[Starlette] | None = None,
) -> Starlette:
    """Own the dependency root and native SDK lifecycle for an MCP-only app."""
    config = settings if settings is not None else get_settings()
    bootstrapper = Bootstrapper(config.app.modules)
    container = make_async_container(
        CoreProvider(config), *bootstrapper.boot_providers(), *providers
    )
    server = (
        server_factory(container)
        if server_factory is not None
        else build_server(
            bootstrapper.boot_mcp_tools(), container, name=config.fastapi.title
        )
    )
    app = server.streamable_http_app(
        **{
            "stateless_http": True,
            "json_response": True,
            **(http_options or {}),
        }
    )
    sdk_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def managed_lifespan(
        app: Starlette,
    ) -> AsyncGenerator[Mapping[str, Any]]:
        try:
            logger.setup(config.logging)
            async with AsyncExitStack() as stack:
                sdk_state = await stack.enter_async_context(sdk_lifespan(app))
                user_state = (
                    await stack.enter_async_context(lifespan(app))
                    if lifespan is not None
                    else None
                )
                yield {**(sdk_state or {}), **(user_state or {})}
        finally:
            with CancelScope(shield=True):
                await container.close()

    app.router.lifespan_context = managed_lifespan
    app.state.dishka_container = container
    app.state.mcp_server = server
    return app
