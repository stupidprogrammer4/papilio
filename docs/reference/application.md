# Application and discovery

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.api.application`

### `create_app`

```python
def create_app(settings: Settings | None=None, *, providers: Sequence[Provider]=(), routers: Sequence[APIRouter]=(), middleware: Sequence[Middleware] | None=None, lifespan: Lifespan[FastAPI] | None=None, exception_handlers: Mapping[int | type[Exception], HTTPExceptionHandler] | None=None, docs_url: str | None='/docs', mcp: bool | Sequence[MCPRouter]=False, mcp_path: str='/mcp', mcp_http_options: Mapping[str, Any] | None=None, **fastapi_options: Any) -> FastAPI:
    ...
```

See [MCP server tools](../guide/mcp.md) for optional discovery, transport options
and per-call Dishka scopes.

## `papilio.api.docs`

### `setup_docs`

```python
def setup_docs(app: FastAPI, *, docs_url: str='/docs', static_url: str='/static/swagger') -> None:
    ...
```

## `papilio.core.bootstrap`

### `Bootstrapper`

```python
class Bootstrapper:
    def __init__(self, base_pkgs: Sequence[str]=()) -> None:
        ...

    @cached_property
    def submodules(self) -> list:
        ...

    def _is_module(self, name: str) -> bool:
        ...

    def import_module(self, path: str, *, raise_nested: bool=False):
        ...

    def import_package_modules(self, path: str, *, raise_nested: bool=False) -> list:
        ...

    def boot_routers(self) -> list[APIRouter]:
        ...

    def boot_mcp_tools(self) -> list[MCPRouter]:
        ...

    def boot_function_tools(self) -> list[FunctionTools]:
        ...

    def boot_sqlmodels(self) -> None:
        ...

    def boot_providers(self) -> list[Provider]:
        ...

    def boot_documents(self) -> list[type[AsyncDocument]]:
        ...

    async def boot_es_indices(self, es: AsyncElasticsearch) -> None:
        ...
```

### `get_bootstrapper`

```python
@lru_cache
def get_bootstrapper() -> Bootstrapper:
    ...
```

## `papilio.core.logger`

```python
request_id_ctx: ContextVar[str | None] = ContextVar('request_id', default=None)
```

### `JSONFormatter`

```python
class JSONFormatter(logging.Formatter):
    BUILTIN_RECORD_ATTRS = frozenset({'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename', 'funcName', 'levelname', 'levelno', 'lineno', 'message', 'module', 'msecs', 'msg', 'name', 'pathname', 'process', 'processName', 'relativeCreated', 'request_id', 'stack_info', 'stacklevel', 'taskName', 'thread', 'threadName'})
    def __init__(self, service: str) -> None:
        ...

    def format(self, record: logging.LogRecord) -> str:
        ...

    @staticmethod
    def _timestamp(created: float) -> str:
        ...
```

### `Logger`

```python
class Logger:
    ADOPTED_LOGGERS = ('uvicorn', 'uvicorn.error', 'uvicorn.access', 'gunicorn.error', 'gunicorn.access')
    def __init__(self, name: str='app', level: int | str=logging.INFO) -> None:
        ...

    def setup(self, config: LoggingConfig) -> None:
        ...

    @staticmethod
    def build_handler(fmt: str, service: str) -> logging.Handler:
        ...

    def set_level(self, level: int | str) -> None:
        ...

    def debug(self, msg: object, *args: Any, **kw: Any) -> None:
        ...

    def info(self, msg: object, *args: Any, **kw: Any) -> None:
        ...

    def warning(self, msg: object, *args: Any, **kw: Any) -> None:
        ...

    def error(self, msg: object, *args: Any, **kw: Any) -> None:
        ...

    def exception(self, msg: object, *args: Any, **kw: Any) -> None:
        ...

    def critical(self, msg: object, *args: Any, **kw: Any) -> None:
        ...
```

```python
logger: Logger = Logger(name='app')
```

## `papilio.providers.base`

### `CoreProvider`

```python
class CoreProvider(Provider):

    def __init__(self, settings: Settings | None=None) -> None:
        ...

    @provide(scope=Scope.APP)
    def settings(self) -> Settings:
        ...
```
