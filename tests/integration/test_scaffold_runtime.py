import os
import subprocess
import sys
from uuid import uuid4

import pytest
import yaml

from papilio.scaffolding import modules, project
from papilio.scaffolding.options import Infrastructure


@pytest.mark.parametrize("cqrs", [False, True])
def test_generated_sql_routes_and_query_tools(tmp_path, cqrs):
    dsn = os.environ.get("PAPILIO_TEST_POSTGRESQL_URL")
    if not dsn:
        pytest.skip("Set PAPILIO_TEST_POSTGRESQL_URL for scaffold SQL checks")
    root = tmp_path / "shop"
    project.write(
        root, "shop", "Shop", cqrs=cqrs, infra=(Infrastructure.POSTGRESQL,)
    )
    target = modules.write(
        root / "shop/modules",
        "shop.modules",
        "product",
        cqrs=cqrs,
        mcp=True,
        function_tools=True,
    )
    read_tool = target / "function_tools/operations.py"
    read_tool.write_text(
        read_tool.read_text().replace(
            "raise NotImplementedError("
            '"Configure Function Tool authorization")',
            'return context in {"permitted", "approved"}',
        )
    )
    context_target = modules.write(
        root / "shop/modules",
        "shop.modules",
        "summary",
        context=True,
        function_tools=True,
    )
    context_tool = context_target / "function_tools/operations.py"
    context_tool.write_text(
        context_tool.read_text()
        .replace(
            "raise NotImplementedError("
            '"Configure Function Tool authorization")',
            'return context in {"permitted", "approved"}',
        )
        .replace(
            'raise NotImplementedError("Configure Function Tool approval")',
            'return context == "approved"',
        )
    )
    (context_target / "domain/context.py").write_text(
        "from pydantic import BaseModel\n"
        "class SummaryContext(BaseModel):\n    name: str\n"
    )
    (context_target / "domain/dtos.py").write_text(
        "from papilio.schemas.inputs import BaseDTO\n"
        "class SummaryInput(BaseDTO):\n    suffix: str\n"
    )
    (context_target / "app/results.py").write_text(
        "from papilio.schemas.outputs import BaseOutput\n"
        "class SummaryOut(BaseOutput):\n    name: str\n"
    )
    context_service = context_target / "app/services.py"
    context_service.write_text(
        context_service.read_text().replace(
            "raise NotImplementedError",
            "return SummaryOut(name=context.name + data.suffix)",
        )
    )
    (context_target / "infra/readers.py").write_text(
        "from sqlalchemy import select\n"
        "from papilio.infra.db.repositories.backends.postgresql "
        "import PGReader\n"
        "from shop.modules.products.infra.tables import ProductTable\n"
        "from shop.modules.summary.domain.context import SummaryContext\n"
        "class SummaryReader(PGReader):\n"
        "    async def read(self) -> SummaryContext:\n"
        "        result = await self.uow.execute(select(ProductTable.name))\n"
        "        return SummaryContext(name=result.scalar_one())\n"
    )
    main_file = root / "shop/main.py"
    main_file.write_text(
        main_file.read_text().replace(
            "create_app(settings,", "create_app(settings, mcp=True,"
        )
    )
    config = yaml.safe_load((root / "config.yml").read_text())
    config["db"]["dsn"] = dsn
    (root / "config.yml").write_text(yaml.safe_dump(config))
    (target / "domain/entities.py").write_text(
        "from papilio.infra.db.schema.entity import PersistenceEntity\n"
        "class ProductModel(PersistenceEntity):\n    name: str\n"
    )
    (target / "domain/dtos.py").write_text(
        "from papilio.schemas.inputs import BaseDTO\n"
        "class ProductCreate(BaseDTO):\n    name: str\n"
        "class ProductUpdate(BaseDTO):\n    name: str | None = None\n"
    )
    table_file = target / "infra/tables.py"
    source = table_file.read_text().replace(
        "    pass", f'    __tablename__ = "scaffold_{uuid4().hex}"'
    )
    # Table templates use an ellipsis rather than pass.
    source = source.replace(
        "    ...", f'    __tablename__ = "scaffold_{uuid4().hex}"'
    )
    table_file.write_text(source)
    script = """
import asyncio
from unittest.mock import AsyncMock
from sqlalchemy import event
from httpx import AsyncClient, ASGITransport
from papilio.core.bootstrap import Bootstrapper
from papilio.infra.db.connection import DBConnection
from papilio.infra.db.uow import PGUnitOfWork
from papilio.function_tools.execution import FunctionToolExecutor

Bootstrapper.boot_es_indices = AsyncMock()
from shop.main import app
from shop.modules.products.infra.tables import ProductTable

if CQRS:
    from shop.modules.products.infra.repository import ProductESStore

    class Hit:
        def to_dict(self):
            return {"name": "read model"}

    class Search:
        def __getitem__(self, page):
            assert page == slice(0, 20)
            return self

        async def execute(self):
            return [Hit()]

    ProductESStore.search = lambda self: Search()


async def main():
    async with app.router.lifespan_context(app):
        database = await app.state.dishka_container.get(
            DBConnection[PGUnitOfWork]
        )
        executor = FunctionToolExecutor(
            Bootstrapper(["shop.modules"]).boot_function_tools(),
            app.state.dishka_container,
        )
        async with database.engine.begin() as conn:
            await conn.run_sync(ProductTable.__table__.create)
        statements = []
        event.listen(
            database.engine.sync_engine,
            "before_cursor_execute",
            lambda conn, cursor, stmt, params, context, many: (
                statements.append(stmt)
            ),
        )
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                response = await client.post(
                    "/products", json={"name": "first"}
                )
                assert response.status_code == 201, response.text
                key = response.json()["data"]["id"]
                assert len(statements) == 1 and statements[0].startswith(
                    "INSERT"
                )
                tool_result = await app.state.mcp_server.call_tool(
                    "products_get", {"id": key}
                )
                assert tool_result.structured_content["id"] == key
                assert tool_result.structured_content["name"] == "first"
                direct = await executor.invoke(
                    "products_get", {"id": key}, context="permitted"
                )
                assert direct.id == key and direct.name == "first"
                try:
                    await executor.invoke(
                        "summary_run", {"data": {"suffix": "!"}},
                        context="permitted",
                    )
                except PermissionError:
                    pass
                else:
                    raise AssertionError("Unapproved context tool executed")
                summary = await executor.invoke(
                    "summary_run", {"data": {"suffix": "!"}},
                    context="approved",
                )
                assert summary.name == "first!"
                statements.clear()
                response = await client.patch(
                    f"/products/{key}", json={"name": "second"}
                )
                assert response.status_code == 200, response.text
                assert response.json()["data"]["name"] == "second"
                assert len(statements) == 1 and statements[0].startswith(
                    "UPDATE"
                )
                response = await client.get(f"/products/{key}")
                assert response.json()["data"]["name"] == "second"
                direct = await executor.invoke(
                    "products_get", {"id": key}, context="permitted"
                )
                assert direct.id == key and direct.name == "second"
                summary = await executor.invoke(
                    "summary_run", {"data": {"suffix": "?"}},
                    context="approved",
                )
                assert summary.name == "second?"
                statements.clear()
                response = await client.delete(f"/products/{key}")
                assert response.json() == 1
                assert len(statements) == 1 and statements[0].startswith(
                    "DELETE"
                )
                assert (
                    await client.get(f"/products/{key}")
                ).status_code == 404
                if CQRS:
                    response = await client.get("/products/search")
                    assert response.status_code == 200, response.text
                    assert response.json() == [{"name": "read model"}]
        finally:
            async with database.engine.begin() as conn:
                await conn.run_sync(ProductTable.__table__.drop)


asyncio.run(main())
""".replace("CQRS", repr(cqrs))
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
