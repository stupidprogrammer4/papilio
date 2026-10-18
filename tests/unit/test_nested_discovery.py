"""Exercise file and nested-package registrations through native discovery."""

import importlib
import sys
from textwrap import dedent

import pytest
from dishka import make_async_container
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel

from papilio.core.bootstrap import Bootstrapper
from papilio.function_tools.execution import FunctionToolExecutor


@pytest.fixture
def application_package(tmp_path, monkeypatch):
    package = "nested_discovery_app"
    root = tmp_path / package
    root.mkdir()
    (root / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    yield package, root
    for name in list(sys.modules):
        if name == package or name.startswith(package + "."):
            del sys.modules[name]
    table = SQLModel.metadata.tables.get("nested_discovery_item")
    if table is not None:
        SQLModel.metadata.remove(table)


def write_source(root, relative, content):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    parent = target.parent
    while parent != root:
        (parent / "__init__.py").touch(exist_ok=True)
        parent = parent.parent
    target.write_text(dedent(content))


@pytest.mark.parametrize("nested", [False, True])
async def test_all_registration_families_accept_files_and_nested_packages(
    application_package, nested
):
    package, root = application_package
    suffix = "/admin/items.py" if nested else ".py"
    sources = {
        "routers" + suffix: """\
            from fastapi import APIRouter
            router = APIRouter()
            alias = router
            @router.get('/items')
            async def items() -> list[int]:
                return [7]
        """,
        "function_tools" + suffix: """\
            from papilio.function_tools.registry import (
                FunctionTools, ToolEffect,
            )
            tools = FunctionTools()
            alias = tools
            async def authorized(context, arguments):
                return True
            @tools.tool(
                key='items.read', name='list_items', title='List items',
                description='List items.', effect=ToolEffect.READ,
                authorize=authorized,
            )
            async def items() -> list[int]:
                return [7]
        """,
        "tools" + suffix: """\
            from papilio.mcp.router import MCPRouter
            tools = MCPRouter()
            alias = tools
            @tools.tool(name='mcp_items')
            async def items() -> list[int]:
                return [7]
        """,
        "providers" + suffix: """\
            from dishka import Provider
            class ItemProvider(Provider): pass
            Alias = ItemProvider
        """,
        "infra/tables" + suffix: """\
            from sqlmodel import SQLModel, Field
            class ItemTable(SQLModel, table=True):
                __tablename__ = 'nested_discovery_item'
                id: int = Field(primary_key=True)
        """,
        "domain/documents" + suffix: """\
            from elasticsearch.dsl import AsyncDocument, Keyword
            class ItemDocument(AsyncDocument):
                title = Keyword()
            Alias = ItemDocument
        """,
        "domain/unrelated.py": "raise AssertionError('unrelated domain')\n",
        "infra/unrelated.py": "raise AssertionError('unrelated infra')\n",
    }
    for relative, source in sources.items():
        write_source(root, relative, source)
    importlib.invalidate_caches()
    bootstrap = Bootstrapper()
    bootstrap.submodules = [package]

    providers = bootstrap.boot_providers()
    assert [type(provider).__name__ for provider in providers] == [
        "ItemProvider"
    ]
    assert "nested_discovery_item" in SQLModel.metadata.tables
    assert [document.__name__ for document in bootstrap.boot_documents()] == [
        "ItemDocument"
    ]
    routers = bootstrap.boot_routers()
    assert len(routers) == 1
    app = FastAPI()
    app.include_router(routers[0])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.get("/items")
    assert response.status_code == 200
    assert response.json() == [7]
    assert len(bootstrap.boot_mcp_tools()) == 1
    assert bootstrap.boot_mcp_tools()[0].tools[0].name == "mcp_items"
    collections = bootstrap.boot_function_tools()
    assert len(collections) == 1
    async with make_async_container() as container:
        executor = FunctionToolExecutor(collections, container)
        assert len(executor.tools) == 1
        result = await executor.invoke("list_items", {}, context=None)
    assert result == [7]


@pytest.mark.parametrize(
    "method,layer",
    [
        ("boot_routers", "routers"),
        ("boot_function_tools", "function_tools"),
        ("boot_mcp_tools", "tools"),
        ("boot_providers", "providers"),
        ("boot_documents", "domain/documents"),
        ("boot_sqlmodels", "infra/tables"),
    ],
)
def test_nested_registration_import_errors_propagate(
    application_package, method, layer
):
    package, root = application_package
    write_source(
        root,
        layer + "/admin/broken.py",
        "import missing_nested_registration_dependency\n",
    )
    importlib.invalidate_caches()
    bootstrap = Bootstrapper()
    bootstrap.submodules = [package]
    with pytest.raises(ModuleNotFoundError) as error:
        getattr(bootstrap, method)()
    assert error.value.name == "missing_nested_registration_dependency"
