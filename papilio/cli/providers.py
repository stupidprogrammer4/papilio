"""List optional providers and show explicit application wiring."""

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from papilio.providers.catalog import PROVIDERS

from .display import panel


def providers(
    name: str | None = typer.Argument(
        None, help="Provider name; omit to list installation availability"
    ),
) -> None:
    if name is None:
        table = Table(
            "Name",
            "Provider",
            "Dependencies",
            "Install extra",
            title="Papilio · Providers",
            title_style="bold cyan",
            header_style="bold cyan",
            box=box.ROUNDED,
            row_styles=["", "dim"],
        )
        for spec in PROVIDERS:
            missing = spec.missing()
            table.add_row(
                spec.name,
                spec.cls,
                "missing: " + ", ".join(missing) if missing else "installed",
                f"papilio[{spec.extra}]",
            )
        Console().print(table)
        typer.echo("Show usage: papilio providers NAME")
        typer.echo(
            "Installed dependencies do not activate providers "
            "or test connectivity."
        )
        return

    spec = next((item for item in PROVIDERS if item.name == name), None)
    if spec is None:
        raise typer.BadParameter(
            "Choose one of: " + ", ".join(item.name for item in PROVIDERS)
        )
    panel(
        spec.name, [f"Provider: {spec.cls}", f"Extra: papilio[{spec.extra}]"]
    )
    missing = spec.missing()
    if missing:
        typer.echo("Missing dependencies: " + ", ".join(missing))
        typer.echo(f"Install: pip install 'papilio[{spec.extra}]'")
    selected = [spec]
    if name == "rate-redis":
        selected.insert(
            0, next(item for item in PROVIDERS if item.name == "redis")
        )
        typer.echo(
            "Enable settings.rate_limit.enabled and include RedisProvider."
        )
    typer.echo("\nfrom papilio.api.application import create_app")
    for item in selected:
        typer.echo(f"from papilio.providers.{item.module} import {item.cls}")
    typer.echo("\napp = create_app(settings, providers=[")
    for item in selected:
        argument = f"settings.{item.config}" if item.config else ""
        typer.echo(f"    {item.cls}({argument}),")
    typer.echo("])")
    if name in {"rate-memory", "rate-redis"}:
        typer.echo(
            "\nFor HTTP limiting, explicitly add RateLimitMiddleware "
            "or route rate_limit dependencies; "
            "enable settings.rate_limit.enabled."
        )
    if name == "es":
        typer.echo(
            "\nIndex initialization is optional; "
            "configure it in your app lifespan."
        )
