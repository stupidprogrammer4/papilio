"""Exercise a base-only wheel installation from outside the checkout."""

import subprocess
import sys
import tempfile
from dataclasses import is_dataclass
from importlib.util import find_spec
from pathlib import Path

import papilio
from papilio.schemas.results import DeleteResult, PatchResult


def main() -> None:
    assert (
        Path(papilio.__file__)
        .resolve()
        .is_relative_to(Path(sys.prefix).resolve())
    )
    value, patch = object(), object()
    result = PatchResult(affected=1, value=value, patch=patch)
    assert (
        is_dataclass(result)
        and result.value is value
        and result.patch is patch
    )
    assert DeleteResult(affected=0, value=None).value is None
    assert find_spec("mcp") is None
    assert find_spec("pydantic_ai") is None
    for module, extra in (
        ("papilio.function_tools.mcp", "papilio[mcp]"),
        (
            "papilio.function_tools.pydantic_ai",
            "papilio[function-tools-pydantic-ai]",
        ),
    ):
        try:
            __import__(module)
        except ImportError as error:
            assert extra in str(error), str(error)
        else:
            raise AssertionError(f"Optional adapter imported without {extra}")

    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(
            [str(Path(sys.executable).with_name("papilio")), "--help"],
            cwd=directory,
            check=True,
        )
        subprocess.run(
            [sys.executable, "-m", "papilio.cli", "run", "--help"],
            cwd=directory,
            check=True,
        )
        from papilio.scaffolding.project import write

        write(Path(directory), "sample", "Sample")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "papilio.cli",
                "module",
                "health",
                "--plain",
                "--function-tools",
            ],
            cwd=directory,
            check=True,
        )
        target = Path(directory) / "sample/modules/health"
        assert (target / "function_tools/operations.py").is_file()
        for relative, before, after in (
            (
                "domain/dtos.py",
                "class HealthInput(BaseDTO): ...",
                "class HealthInput(BaseDTO):\n    message: str",
            ),
            (
                "app/results.py",
                "class HealthOut(BaseOutput): ...",
                "class HealthOut(BaseOutput):\n    message: str",
            ),
            (
                "app/services.py",
                "return HealthOut()",
                "return HealthOut(message=data.message)",
            ),
        ):
            path = target / relative
            source = path.read_text()
            assert before in source
            path.write_text(source.replace(before, after))
        subprocess.run(
            [
                sys.executable,
                "-c",
                """
import asyncio
from collections.abc import Mapping
from typing import Any
from dishka import FromDishka
from papilio.core.bootstrap import Bootstrapper
from papilio.function_tools.execution import FunctionToolExecutor
from papilio.function_tools.registry import FunctionTools, ToolEffect
from sample.main import app
from sample.modules.health.app.results import HealthOut
from sample.modules.health.domain.dtos import HealthInput
from sample.modules.health.interfaces import IHealthService

assert app.title == "Sample"
assert app.openapi()["info"]["title"] == "Sample"
tools = FunctionTools()

async def authorize(context: Any, arguments: Mapping[str, Any]) -> bool:
    return context == "permitted"

@tools.tool(
    key="health.echo", name="echo", title="Echo health input",
    description="Execute the generated application service.",
    effect=ToolEffect.READ, authorize=authorize,
)
async def echo(
    data: HealthInput, service: FromDishka[IHealthService]
) -> HealthOut:
    result = await service.run(data)
    return result

async def run():
    async with app.router.lifespan_context(app):
        discovered = Bootstrapper(["sample.modules"]).boot_function_tools()
        assert [tool.name for item in discovered for tool in item.tools] == [
            "health_run"
        ]
        executor = FunctionToolExecutor(
            [*discovered, tools], app.state.dishka_container
        )
        try:
            await executor.invoke(
                "health_run", {"data": {"message": "input"}},
                context="permitted",
            )
        except NotImplementedError:
            pass
        else:
            raise AssertionError("Generated policy did not fail closed")
        result = await executor.invoke(
            "echo", {"data": {"message": "native service result"}},
            context="permitted",
        )
        assert result.message == "native service result"
        try:
            await executor.invoke(
                "echo", {"data": {"message": "denied"}}, context="denied"
            )
        except PermissionError:
            pass
        else:
            raise AssertionError("Unauthorized tool executed")

asyncio.run(run())
""",
            ],
            cwd=directory,
            check=True,
        )
    print(
        "Installed base wheel, CLI, templates, Function Tools, "
        "optional boundaries, result dataclasses and app passed"
    )


if __name__ == "__main__":
    main()
