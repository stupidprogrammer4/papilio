"""Exercise a base-only wheel installation from outside the checkout."""

import subprocess
import sys
import tempfile
from dataclasses import is_dataclass
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
                "-c",
                "import asyncio\n"
                "from sample.main import app\n"
                "assert app.title == 'Sample'\n"
                "assert app.openapi()['info']['title'] == 'Sample'\n"
                "async def run():\n"
                "    async with app.router.lifespan_context(app):\n"
                "        pass\n"
                "asyncio.run(run())\n",
            ],
            cwd=directory,
            check=True,
        )
    print("Installed wheel, CLI, templates, result dataclasses and app passed")


if __name__ == "__main__":
    main()
