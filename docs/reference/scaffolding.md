# CLI and scaffolding

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.cli.app`

```python
app: typer.Typer
```

`papilio --help` groups commands for building, running and exploring applications. `papilio --version` prints the installed package version.

## `papilio run`

| Option | Purpose |
| --- | --- |
| `--app module:app` | ASGI application object |
| `--backend uvicorn\|gunicorn\|fastapi` | Native server launcher |
| `--mode dev\|prod` | Development or production defaults |
| `--host ADDRESS` | Listening address |
| `--port INTEGER` | Listening port, 1–65535 |
| `--workers INTEGER` | Positive worker count; dev requires one |
| `--reload / --no-reload` | Restart after code changes |
| `--config PATH` | Selected YAML configuration |

See [runner installation, configuration and precedence](../guide/operations.md).

## `papilio.cli.modules`

### `module`

```python
def module(name: str=typer.Argument(..., help='<name> or <group>.<name>'), cqrs: bool=typer.Option(False, '--cqrs', help='Add ES documents and CQRS tools'), context: bool=typer.Option(False, '--context', help='Generate a context module'), plain: bool=typer.Option(False, '--plain', help='Module without a database'), http: bool=typer.Option(False, '--http', help='Add an HTTP gateway'), excel: bool=typer.Option(False, '--excel', help='Add an exporter')) -> None:
    ...
```

## `papilio.cli.project`

### `new`

```python
def new(name: str=typer.Argument(..., help='Project name'), directory: str=typer.Option('', '--dir', help='Destination directory'), infra: list[Infrastructure]=typer.Option([], '--infra', help='Optional infrastructure; repeat to select several'), cqrs: bool=typer.Option(False, '--cqrs', help='Enable Elasticsearch')) -> None:
    ...
```

## `papilio.scaffolding.modules`

### `files`

```python
def files(package: str, name: str, *, cqrs: bool=False, context: bool=False, plain: bool=False, http: bool=False, excel: bool=False) -> dict[str, str]:
    ...
```

### `write`

```python
def write(root: Path, package: str, name: str, *, cqrs: bool=False, context: bool=False, plain: bool=False, http: bool=False, excel: bool=False) -> Path:
    ...
```

## `papilio.scaffolding.options`

### `Infrastructure`

```python
class Infrastructure(StrEnum):
    POSTGRESQL = 'postgresql'
    ES = 'es'
    REDIS = 'redis'
    RATE_LIMIT = 'rate-limit'
    HTTP = 'http'
    EXCEL = 'excel'
    FILES = 'files'
    CSV = 'csv'
```

## `papilio.scaffolding.project`

### `files`

```python
def files(package: str, name: str, *, cqrs: bool=False, infra: Sequence[Infrastructure]=()) -> dict[str, str]:
    ...
```

### `write`

```python
def write(root: Path, package: str, name: str, *, cqrs: bool=False, infra: Sequence[Infrastructure]=()) -> list[Path]:
    ...
```

## `papilio.scaffolding.templates`

### `render`

```python
def render(template: str, values: Mapping[str, str]) -> str:
    ...
```

## `papilio.cli.providers`

### `providers`

```python
def providers(name: str | None=typer.Argument(None, help='Provider name; omit to list installation availability')) -> None:
    ...
```
