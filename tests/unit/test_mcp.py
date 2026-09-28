"""MCP contracts exercised through the SDK and real Dishka providers."""

from __future__ import annotations

import asyncio
import importlib
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import anyio
import httpx2
import pytest
import yaml
from dishka import FromDishka, Provider, Scope, provide
from dishka.integrations.fastapi import DishkaRoute
from fastapi import APIRouter
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from pydantic import BaseModel
from sqlalchemy import text

from papilio.api.application import create_app
from papilio.core.bootstrap import Bootstrapper
from papilio.core.config import DatabaseConfig, Settings
from papilio.errors.exceptions import ForbiddenException
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.tools.decorators import transactional
from papilio.infra.db.uow import SQLiteUnitOfWork, UnitOfWork
from papilio.mcp.router import MCPRouter
from papilio.providers.db import SQLiteProvider
from papilio.scaffolding import modules, project


@pytest.fixture
def settings(monkeypatch):
    monkeypatch.setattr("papilio.api.application.logger.setup", lambda _: None)
    settings = Settings.model_validate(
        yaml.safe_load(project.files("shop", "Shop")["config.yml"])
    )
    settings.app.modules = []
    return settings


@asynccontextmanager
async def protocol_client(app, *, mode="auto", path="/mcp/"):
    async with httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),
        base_url="http://localhost:8000",
    ) as http:
        transport = streamable_http_client(
            f"http://localhost:8000{path}", http_client=http
        )
        async with Client(transport, mode=mode) as client:
            yield client, http


@dataclass
class Shared:
    closed: int = 0


@dataclass
class PerCall:
    shared: Shared
    closed: bool = False


class CallProvider(Provider):
    def __init__(self):
        super().__init__()
        self.calls: list[PerCall] = []
        self.shared = Shared()

    @provide(scope=Scope.APP)
    async def app_resource(self) -> AsyncGenerator[Shared]:
        try:
            yield self.shared
        finally:
            self.shared.closed += 1

    @provide(scope=Scope.REQUEST)
    async def call_resource(self, shared: Shared) -> AsyncGenerator[PerCall]:
        resource = PerCall(shared)
        self.calls.append(resource)
        try:
            yield resource
        finally:
            await anyio.sleep(0)
            resource.closed = True


class ToolInput(BaseModel):
    value: int


class ToolOutput(BaseModel):
    doubled: int
    app_id: int


class RecordService:
    def __init__(self, unit: SQLiteUnitOfWork):
        self.unit = unit

    @transactional
    async def write(self, value: int, fail: bool) -> int:
        assert UnitOfWork.current() is self.unit
        await self.uncommitted(value)
        if fail:
            raise ForbiddenException("Rejected write", "rejected")
        return value

    async def uncommitted(self, value: int) -> int:
        await self.unit.execute(
            text("INSERT INTO records (id) VALUES (:id)"), {"id": value}
        )
        return value


class RecordProvider(Provider):
    service = provide(RecordService, scope=Scope.REQUEST)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
async def test_wire_schema_validation_injection_and_http_sharing(
    settings, mode
):
    provider = CallProvider()
    tools = MCPRouter()

    @tools.tool(description="Double a value")
    async def double(
        data: ToolInput, service: FromDishka[PerCall]
    ) -> ToolOutput:
        assert not service.closed
        return ToolOutput(doubled=data.value * 2, app_id=id(service.shared))

    router = APIRouter(route_class=DishkaRoute)

    @router.get("/identity")
    async def identity(shared: FromDishka[Shared]):
        return {"id": id(shared)}

    app = create_app(
        settings, mcp=[tools], providers=[provider], routers=[router]
    )
    async with app.router.lifespan_context(app):
        async with protocol_client(app, mode=mode) as (client, http):
            listed = (await client.list_tools()).tools
            assert len(listed) == 1
            assert listed[0].name == "double"
            assert set(listed[0].input_schema["properties"]) == {"data"}
            assert listed[0].output_schema is not None
            result = await client.call_tool(
                "double", {"data": {"value": 3}, "service": "untrusted"}
            )
            assert not result.is_error
            assert result.structured_content == {
                "doubled": 6,
                "app_id": id(provider.shared),
            }
            assert (await http.get("/identity")).json()["id"] == id(
                provider.shared
            )
            invalid = await client.call_tool(
                "double", {"data": {"value": "bad"}}
            )
            assert invalid.is_error
            assert len(provider.calls) == 1
            assert provider.calls[0].closed
            assert provider.shared.closed == 0
    assert provider.shared.closed == 1


async def test_concurrent_calls_and_apps_do_not_share_request_resources(
    settings,
):
    tools = MCPRouter()
    entered = 0
    both_entered = asyncio.Event()

    @tools.tool()
    async def identity(service: FromDishka[PerCall]) -> int:
        nonlocal entered
        entered += 1
        if entered == 2:
            both_entered.set()
        await asyncio.wait_for(both_entered.wait(), 5)
        assert not service.closed
        return id(service)

    providers = [CallProvider(), CallProvider()]
    apps = [
        create_app(settings, mcp=[tools], providers=[p]) for p in providers
    ]
    async with apps[0].router.lifespan_context(apps[0]):
        async with apps[1].router.lifespan_context(apps[1]):
            results = await asyncio.gather(
                apps[0].state.mcp_server.call_tool("identity", {}),
                apps[0].state.mcp_server.call_tool("identity", {}),
                apps[1].state.mcp_server.call_tool("identity", {}),
            )
            assert len({r.structured_content["result"] for r in results}) == 3
            assert all(r.closed for p in providers for r in p.calls)
            assert all(
                r.shared is p.shared for p in providers for r in p.calls
            )
        assert providers[1].shared.closed == 1
        assert providers[0].shared.closed == 0
    assert providers[0].shared.closed == 1


async def test_errors_cleanup_and_hide_unexpected_details(settings):
    provider = CallProvider()
    tools = MCPRouter()

    @tools.tool()
    async def fail(kind: str, service: FromDishka[PerCall]) -> str:
        if kind == "known":
            raise ForbiddenException("Access denied", "denied")
        raise RuntimeError("SECRET database detail")

    app = create_app(settings, mcp=[tools], providers=[provider])
    async with app.router.lifespan_context(app):
        async with protocol_client(app) as (client, _):
            for kind in ["known", "unexpected"]:
                result = await client.call_tool("fail", {"kind": kind})
                assert result.is_error
                text = str(result.content)
                assert "SECRET" not in text
                if kind == "known":
                    assert "denied" in text
                assert provider.calls[-1].closed


async def test_cancellation_finalizes_async_provider(settings):
    provider = CallProvider()
    tools = MCPRouter()
    entered = anyio.Event()
    cancelled = anyio.Event()

    @tools.tool()
    async def wait(service: FromDishka[PerCall]) -> str:
        entered.set()
        await anyio.sleep_forever()
        return "unreachable"

    app = create_app(settings, mcp=[tools], providers=[provider])
    async with app.router.lifespan_context(app):
        with anyio.fail_after(5):
            async with anyio.create_task_group() as group:

                async def call():
                    with anyio.CancelScope() as scope:
                        cancel_scopes.append(scope)
                        try:
                            await app.state.mcp_server.call_tool("wait", {})
                        finally:
                            cancelled.set()

                cancel_scopes = []
                group.start_soon(call)
                await entered.wait()
                cancel_scopes[0].cancel()
                await cancelled.wait()
        assert provider.calls[0].closed
        assert provider.shared.closed == 0
    assert provider.shared.closed == 1


@pytest.mark.parametrize("fail", ["startup", "shutdown", None])
async def test_lifespan_state_and_single_container_owner(settings, fail):
    provider = CallProvider()

    @asynccontextmanager
    async def lifespan(app):
        await app.state.dishka_container.get(Shared)
        if fail == "startup":
            raise ValueError("startup")
        yield {"example": "state"}
        assert provider.shared.closed == 0
        if fail == "shutdown":
            raise ValueError("shutdown")

    app = create_app(
        settings, mcp=True, providers=[provider], lifespan=lifespan
    )

    async def run():
        async with app.router.lifespan_context(app) as state:
            assert state == {"example": "state"}
            async with protocol_client(app) as (client, _):
                assert (await client.list_tools()).tools == []

    if fail:
        # The SDK's AnyIO task group may wrap a lifespan exception.
        with pytest.raises((ValueError, ExceptionGroup)):
            await run()
    else:
        await run()
    assert provider.shared.closed == 1


@pytest.mark.parametrize("first_name", [None, ""])
def test_registration_rejects_collisions_and_non_async_handlers(
    settings, first_name
):
    first, second = MCPRouter(), MCPRouter()

    async def same(value: int) -> int:
        return value

    first.tool(name=first_name)(same)
    second.tool()(same)
    with pytest.raises(ValueError, match="Duplicate MCP tool name"):
        create_app(settings, mcp=[first, second])
    first.tool()(same)
    with pytest.raises(ValueError, match="Duplicate MCP tool name"):
        create_app(settings, mcp=[first])
    with pytest.raises(TypeError, match="async function"):
        first.tool()(lambda: 1)  # pyright: ignore[reportArgumentType]


async def test_repeated_router_registration_is_idempotent(settings):
    tools = MCPRouter()

    @tools.tool()
    async def ping() -> str:
        return "pong"

    app = create_app(settings, mcp=[tools, tools])
    async with app.router.lifespan_context(app):
        async with protocol_client(app) as (client, _):
            assert len((await client.list_tools()).tools) == 1
            assert (await client.call_tool("ping", {})).structured_content == {
                "result": "pong"
            }


async def test_discovered_generated_plain_module_calls_its_service(
    settings, tmp_path, monkeypatch
):
    package = "mcp_scaffold"
    root = tmp_path / package
    for name in ("health", "catalog.assistant"):
        modules.write(root, package, name, plain=True, mcp=True)
    modules.write(root, package, "without_tools", plain=True)
    monkeypatch.syspath_prepend(str(tmp_path))
    settings.app.modules = [package]
    importlib.invalidate_caches()
    try:
        discovered = Bootstrapper([package]).boot_mcp_tools()
        assert len(discovered) == 2
        app = create_app(settings, mcp=True)
        async with app.router.lifespan_context(app):
            async with protocol_client(app) as (client, _):
                assert {t.name for t in (await client.list_tools()).tools} == {
                    "health_run",
                    "catalog_assistant_run",
                }
                for name in ("health_run", "catalog_assistant_run"):
                    result = await client.call_tool(name, {"data": {}})
                    assert not result.is_error
                    assert result.structured_content == {}
    finally:
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]


def test_discovery_disabled_and_broken_tools_imports(
    settings, tmp_path, monkeypatch
):
    package = "mcp_broken"
    root = tmp_path / package
    target = modules.write(root, package, "health", plain=True, mcp=True)
    (target / "tools/operations.py").write_text(
        "import missing_mcp_dependency\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    settings.app.modules = [package]
    importlib.invalidate_caches()
    try:
        create_app(settings)
        with pytest.raises(
            ModuleNotFoundError, match="missing_mcp_dependency"
        ):
            create_app(settings, mcp=True)
    finally:
        for name in list(sys.modules):
            if name == package or name.startswith(package + "."):
                del sys.modules[name]


async def test_database_commit_rollback_and_uow_lifetime(settings, tmp_path):
    config = DatabaseConfig(
        dsn=f"sqlite+aiosqlite:///{tmp_path}/mcp.db",
        test_dsn="",
        pool_size=4,
        max_overflow=0,
        pool_timeout=5,
        pool_recycle=1800,
    )
    tools = MCPRouter()
    units = []

    @tools.tool()
    async def write(
        value: int, fail: bool, service: FromDishka[RecordService]
    ) -> int:
        units.append(service.unit)
        return await service.write(value, fail)

    @tools.tool()
    async def uncommitted(
        value: int, service: FromDishka[RecordService]
    ) -> int:
        units.append(service.unit)
        return await service.uncommitted(value)

    app = create_app(
        settings,
        mcp=[tools],
        providers=[SQLiteProvider(config), RecordProvider()],
    )
    async with app.router.lifespan_context(app):
        db = await app.state.dishka_container.get(
            DBConnection[SQLiteUnitOfWork]
        )
        async with db.engine.begin() as connection:
            await connection.execute(text("CREATE TABLE records (id INTEGER)"))
        async with protocol_client(app) as (client, _):
            success = await client.call_tool(
                "write", {"value": 1, "fail": False}
            )
            failure = await client.call_tool(
                "write", {"value": 2, "fail": True}
            )
            pending = await client.call_tool("uncommitted", {"value": 3})
            assert (
                not success.is_error
                and failure.is_error
                and not pending.is_error
            )
        assert len({id(unit) for unit in units}) == 3
        assert all(not unit.is_open for unit in units)
        assert UnitOfWork.current() is None
        async with db.session_factory() as observer:
            assert list(
                await observer.scalars(text("SELECT id FROM records"))
            ) == [1]


async def test_custom_mount_and_native_transport_settings(settings):
    from mcp.server.transport_security import TransportSecuritySettings

    app = create_app(
        settings,
        mcp=True,
        mcp_path="/agent",
        mcp_http_options={
            "transport_security": TransportSecuritySettings(
                allowed_hosts=["localhost:8000"],
                allowed_origins=["https://allowed.example"],
            )
        },
        root_path="/gateway",
    )
    async with app.router.lifespan_context(app):
        async with protocol_client(app, path="/gateway/agent/") as (
            client,
            http,
        ):
            assert (await client.list_tools()).tools == []
            denied = await http.post(
                "/gateway/agent/",
                headers={"Origin": "https://other.example"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
            assert denied.status_code == 403
            assert (await http.get("/gateway/mcp/")).status_code == 404
