"""Generate a web application project."""

from pathlib import Path

import typer

from papilio.scaffolding import project
from papilio.scaffolding.options import Infrastructure

from .display import error, panel


def new(
    name: str = typer.Argument(..., help="Project name"),
    directory: str = typer.Option("", "--dir", help="Destination directory"),
    infra: list[Infrastructure] = typer.Option(
        [], "--infra", help="Optional infrastructure; repeat to select several"
    ),
    cqrs: bool = typer.Option(False, "--cqrs", help="Enable Elasticsearch"),
) -> None:
    package = name.strip().replace("-", "_").replace(" ", "_").lower()
    root = Path(directory) if directory else Path(package)
    try:
        project.write(root, package, name, cqrs=cqrs, infra=infra)
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except FileExistsError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc
    panel(
        "Project created",
        [
            f"Created project at {root}",
            "",
            f"cd {root}",
            'pip install -e ".[dev]"',
            "Edit config.yml, then:",
            "papilio run",
        ],
        style="green",
    )
