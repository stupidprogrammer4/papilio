"""Papilio command-line entry point."""

from importlib.metadata import version

import typer

from .modules import module
from .project import new
from .providers import providers
from .run import run

app = typer.Typer(
    help="[bold cyan]Papilio[/] · Build, run and explore your application.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
    epilog="Start with [cyan]papilio new shop[/], then [cyan]papilio run[/].",
)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"Papilio {version('papilio')}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version,
        is_eager=True,
        help="Show the installed version",
    ),
) -> None:
    pass


app.command(rich_help_panel="Build", help="Create an application project")(new)
app.command(rich_help_panel="Build", help="Add a feature module")(module)
app.command(rich_help_panel="Run")(run)
app.command(
    rich_help_panel="Explore", help="Inspect optional providers and usage"
)(providers)
