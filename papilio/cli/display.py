"""Shared terminal presentation, using Rich's automatic color detection."""

from collections.abc import Sequence

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def panel(title: str, lines: Sequence[str], *, style: str = "cyan") -> None:
    Console().print(
        Panel(
            Text("\n".join(lines)),
            title=Text(title),
            title_align="left",
            border_style=style,
            expand=False,
        )
    )


def details(title: str, values: Sequence[tuple[str, str]]) -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    for key, value in values:
        table.add_row(Text(key), Text(value, overflow="fold"))
    Console().print(
        Panel(
            table, title=Text(title), title_align="left", border_style="cyan"
        )
    )


def error(message: str) -> None:
    Console(stderr=True).print(
        Panel(Text(message), title="Error", border_style="red", expand=False)
    )
