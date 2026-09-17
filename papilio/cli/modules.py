"""Generate a module in the configured application package."""

import importlib
import sys
from pathlib import Path

import typer

from papilio.core.config import get_settings
from papilio.scaffolding import modules

from .display import error, panel


def _target_package() -> tuple[str, Path]:
    """Resolve the current application's module package."""
    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    try:
        packages = get_settings().app.modules
    except FileNotFoundError:
        raise typer.BadParameter(
            "no config.yml here — run this inside a project "
            "(or create one with `papilio new <name>`)"
        ) from None
    if not packages:
        raise typer.BadParameter(
            "configure app.modules before creating a module"
        )
    name = packages[0]
    try:
        package = importlib.import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name and not name.startswith(f"{error.name}."):
            raise
        raise typer.BadParameter(
            f"app.modules names {name!r}, which is not importable from here"
        ) from None
    return name, Path(next(iter(package.__path__)))


def module(
    name: str = typer.Argument(..., help="<name> or <group>.<name>"),
    cqrs: bool = typer.Option(
        False, "--cqrs", help="Add ES documents and CQRS tools"
    ),
    context: bool = typer.Option(
        False, "--context", help="Generate a context module"
    ),
    plain: bool = typer.Option(
        False, "--plain", help="Module without a database"
    ),
    http: bool = typer.Option(False, "--http", help="Add an HTTP gateway"),
    excel: bool = typer.Option(False, "--excel", help="Add an exporter"),
) -> None:
    package, root = _target_package()
    try:
        target = modules.write(
            root,
            package,
            name,
            cqrs=cqrs,
            context=context,
            plain=plain,
            http=http,
            excel=excel,
        )
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except FileExistsError as exc:
        error(str(exc))
        raise typer.Exit(1) from exc
    panel("Module created", [f"Created module at {target}"], style="green")
    extras = set() if plain else {"postgresql"}
    if cqrs:
        extras.add("es")
    if http:
        extras.add("http")
    if excel:
        extras.add("excel")
    if extras:
        typer.echo(
            "Required extras: papilio[" + ",".join(sorted(extras)) + "]"
        )
        typer.echo(
            "Select these extras in your project dependencies "
            "and wire their providers in main.py."
        )
