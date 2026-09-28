"""Build a web application with its own dependencies."""

from __future__ import annotations

from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from typing import TYPE_CHECKING, Any

from dishka import Provider, make_async_container
from dishka.integrations.fastapi import FastapiProvider, setup_dishka
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware import Middleware
from starlette.types import HTTPExceptionHandler, Lifespan

from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import Settings, get_settings
from papilio.core.logger import logger
from papilio.providers.base import CoreProvider

from .docs import setup_docs
from .middlewares.logging import LoggingMiddleware
from .responses.handlers import setup_exception_handlers

if TYPE_CHECKING:
    from papilio.mcp.router import MCPRouter


def create_app(
    settings: Settings | None = None,
    *,
    providers: Sequence[Provider] = (),
    routers: Sequence[APIRouter] = (),
    middleware: Sequence[Middleware] | None = None,
    lifespan: Lifespan[FastAPI] | None = None,
    exception_handlers: Mapping[int | type[Exception], HTTPExceptionHandler]
    | None = None,
    docs_url: str | None = "/docs",
    mcp: bool | Sequence[MCPRouter] = False,
    mcp_path: str = "/mcp",
    mcp_http_options: Mapping[str, Any] | None = None,
    **fastapi_options: Any,
) -> FastAPI:
    """Build an app; extra options go directly to FastAPI."""
    config = settings if settings is not None else get_settings()
    bootstrapper = Bootstrapper(config.app.modules)
    discovered = bootstrapper.boot_providers()
    discovered_routers = bootstrapper.boot_routers()
    container = make_async_container(
        FastapiProvider(),
        CoreProvider(config),
        *discovered,
        *providers,
    )
    mcp_app = None
    mcp_server = None
    if mcp is not False:
        from papilio.mcp.server import build_server

        if not mcp_path.startswith("/") or mcp_path == "/":
            raise ValueError("mcp_path must be a non-root absolute URL path")
        transport_options = dict(mcp_http_options or {})
        if "streamable_http_path" in transport_options:
            raise ValueError("Use mcp_path to select the MCP endpoint")
        mcp_server = build_server(
            (*bootstrapper.boot_mcp_tools(), *(() if mcp is True else mcp)),
            container,
            name=fastapi_options.get("title", config.fastapi.title),
        )
        mcp_app = mcp_server.streamable_http_app(
            streamable_http_path="/",
            **{
                "stateless_http": True,
                "json_response": True,
                **transport_options,
            },
        )

    @asynccontextmanager
    async def managed_lifespan(
        app: FastAPI,
    ) -> AsyncGenerator[Mapping[str, Any]]:
        try:
            logger.setup(config.logging)
            async with AsyncExitStack() as stack:
                if mcp_app is not None:
                    await stack.enter_async_context(
                        mcp_app.router.lifespan_context(mcp_app)
                    )
                state = (
                    await stack.enter_async_context(lifespan(app))
                    if lifespan is not None
                    else None
                )
                yield state or {}
        finally:
            await container.close()

    if middleware is None:
        middleware = (
            Middleware(LoggingMiddleware),
            Middleware(GZipMiddleware, minimum_size=4096),
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        )
    options = {
        "title": config.fastapi.title,
        "description": config.fastapi.description,
        "version": config.fastapi.version,
        "redoc_url": None,
        **fastapi_options,
    }
    app = FastAPI(
        **options,
        docs_url=None,
        lifespan=managed_lifespan,
        middleware=middleware,
    )
    setup_dishka(container, app)
    setup_exception_handlers(app)
    for key, handler in (exception_handlers or {}).items():
        app.add_exception_handler(key, handler)
    if docs_url is not None and app.openapi_url is not None:
        setup_docs(app, docs_url=docs_url)
    for router in (*discovered_routers, *routers):
        app.include_router(router)
    if mcp_app is not None:
        app.state.mcp_server = mcp_server
        app.mount(mcp_path, mcp_app, name="mcp")
    return app
