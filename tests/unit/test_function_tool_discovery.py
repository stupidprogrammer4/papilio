import asyncio
import importlib
import sys

import pytest
from dishka import make_async_container

from papilio.core.bootstrap import Bootstrapper
from papilio.function_tools.execution import FunctionToolExecutor
from papilio.scaffolding import modules


@pytest.fixture
def function_package(tmp_path, monkeypatch):
    package = "function_scaffold"
    root = tmp_path / package
    monkeypatch.syspath_prepend(str(tmp_path))
    yield package, root
    for name in list(sys.modules):
        if name == package or name.startswith(package + "."):
            del sys.modules[name]


def test_discovery_collects_direct_grouped_explicit_tools_once(
    function_package,
):
    package, root = function_package
    direct = modules.write(
        root, package, "health", plain=True, function_tools=True
    )
    modules.write(
        root, package, "catalog.assistant", plain=True, function_tools=True
    )
    modules.write(root, package, "without_tools", plain=True)
    (direct / "function_tools/alias.py").write_text(
        f"from {package}.health.function_tools.operations import tools\n"
    )
    importlib.invalidate_caches()
    discovered = Bootstrapper([package]).boot_function_tools()
    assert len(discovered) == 2
    assert {
        tool.name for collection in discovered for tool in collection.tools
    } == {
        "health_run",
        "catalog_assistant_run",
    }


def test_function_tools_import_only_when_requested(function_package):
    package, root = function_package
    target = modules.write(
        root, package, "health", plain=True, function_tools=True
    )
    (target / "function_tools/operations.py").write_text(
        "import missing_function_dependency\n"
    )
    importlib.invalidate_caches()
    bootstrap = Bootstrapper([package])
    assert len(bootstrap.boot_providers()) == 1
    assert len(bootstrap.boot_routers()) == 1
    with pytest.raises(
        ModuleNotFoundError, match="missing_function_dependency"
    ):
        bootstrap.boot_function_tools()


def test_generated_policy_requires_application_implementation(
    function_package,
):
    package, root = function_package
    modules.write(root, package, "health", plain=True, function_tools=True)
    importlib.invalidate_caches()
    operations = importlib.import_module(
        f"{package}.health.function_tools.operations"
    )
    with pytest.raises(NotImplementedError, match="authorization"):
        asyncio.run(operations.authorize_run(object(), {}))
    with pytest.raises(NotImplementedError, match="approval"):
        asyncio.run(operations.approve_run(object(), {}))


async def test_generated_tool_invokes_its_native_scoped_service(
    function_package,
):
    package, root = function_package
    target = modules.write(
        root, package, "health", plain=True, function_tools=True
    )
    policy = target / "function_tools/operations.py"
    policy.write_text(
        policy.read_text()
        .replace(
            "raise NotImplementedError("
            '"Configure Function Tool authorization")',
            'return context == "permitted"',
        )
        .replace(
            'raise NotImplementedError("Configure Function Tool approval")',
            'return arguments["data"].message == "approved"',
        )
    )
    dto = target / "domain/dtos.py"
    dto.write_text(
        dto.read_text().replace(
            "class HealthInput(BaseDTO): ...",
            "class HealthInput(BaseDTO):\n    message: str\n",
        )
    )
    output = target / "app/results.py"
    output.write_text(
        output.read_text().replace(
            "class HealthOut(BaseOutput): ...",
            "class HealthOut(BaseOutput):\n    message: str\n",
        )
    )
    service = target / "app/services.py"
    service.write_text(
        service.read_text().replace(
            "return HealthOut()", "return HealthOut(message=data.message)"
        )
    )
    importlib.invalidate_caches()
    bootstrap = Bootstrapper([package])
    container = make_async_container(*bootstrap.boot_providers())
    try:
        executor = FunctionToolExecutor(
            bootstrap.boot_function_tools(), container
        )
        assert "service" not in executor.tools[0].input_schema.get(
            "properties", {}
        )
        result = await executor.invoke(
            "health_run",
            {"data": {"message": "approved"}},
            context="permitted",
        )
        assert result.message == "approved"
        with pytest.raises(PermissionError, match="access denied"):
            await executor.invoke(
                "health_run",
                {"data": {"message": "approved"}},
                context="denied",
            )
        with pytest.raises(PermissionError, match="approval required"):
            await executor.invoke(
                "health_run",
                {"data": {"message": "unapproved"}},
                context="permitted",
            )
    finally:
        await container.close()
