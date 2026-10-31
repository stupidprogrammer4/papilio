# Files, CSV and Excel

Generated from this checkout. Code blocks show signatures; `...` replaces implementation bodies. These are reference declarations, not standalone executable modules.

Single-underscore methods are protected extension tools. For inherited methods, follow the base class reference. Localized string values use Unicode escapes.

## `papilio.infra.csv.reader`

### `CSVReader`

```python
class CSVReader:
    @asynccontextmanager
    async def rows(self, path: str | PathLike[str], *, encoding: str='utf-8', delimiter: str=',', quotechar: str | None='"', escapechar: str | None=None, doublequote: bool=True, skipinitialspace: bool=False, strict: bool=True, batch_size: int=1000) -> AsyncGenerator[AsyncIterator[list[str]]]:
        ...
```

## `papilio.infra.csv.writer`

### `CSVStreamWriter`

```python
class CSVStreamWriter:
    def __init__(self, writer: Writer) -> None:
        ...

    async def write_row(self, row: Iterable[object]) -> int:
        ...

    async def write_rows(self, rows: Iterable[Iterable[object]]) -> int:
        ...

    def _write_rows(self, rows: Iterable[Iterable[object]]) -> int:
        ...
```

### `CSVWriter`

```python
class CSVWriter:
    @asynccontextmanager
    async def open(self, path: str | PathLike[str], *, mode: Literal['w', 'a', 'x']='w', encoding: str='utf-8', delimiter: str=',', quotechar: str | None='"', escapechar: str | None=None, doublequote: bool=True, quoting: int=csv.QUOTE_MINIMAL, lineterminator: str='\r\n') -> AsyncGenerator[CSVStreamWriter]:
        ...
```

## `papilio.infra.excel.reader`

### `ExcelReader`

```python
class ExcelReader:
    def __init__(self, max_workers: int=1) -> None:
        ...

    @staticmethod
    def _read_rows_job[TRow: ExcelRow](path: str, sheet: str | None, start_row: int, row_model: type[TRow], max_rows: int | None) -> list[TRow]:
        ...

    @staticmethod
    def _read_cell_job(path: str, sheet: str | None, cell: str) -> Any:
        ...

    async def read_rows[TRow: ExcelRow](self, path: str, row_model: type[TRow], *, start_row: int, sheet: str | None=None, limit: int | None=None) -> list[TRow]:
        ...

    async def read_cell(self, path: str, cell: str, *, sheet: str | None=None) -> Any:
        ...

    async def close(self) -> None:
        ...
```

## `papilio.infra.excel.row`

### `Row`

```python
def Row(*, title: str | None=None, **kwargs: Any) -> Any:
    ...
```

### `ExcelRow`

```python
class ExcelRow(BaseModel):
    column_names: ClassVar[tuple[str, ...]] = ()
    @classmethod
    def titles(cls) -> list[str]:
        ...

    def cells(self) -> list[Any]:
        ...
```

## `papilio.infra.excel.writer`

### `ExcelWriter`

```python
class ExcelWriter:
    def __init__(self, max_workers: int=1) -> None:
        ...

    @staticmethod
    def _write_rows_job(template: str, output: str, sheet: str | None, start_row: int, with_titles: bool, rows: Sequence[ExcelRow]) -> str:
        ...

    @staticmethod
    def _write_cell_job(template: str, output: str, sheet: str | None, cell: str, value: Any) -> str:
        ...

    async def write_rows(self, template: str, output: str, rows: Sequence[ExcelRow], *, start_row: int, sheet: str | None=None, with_titles: bool=False) -> str:
        ...

    async def write_cell(self, template: str, output: str, cell: str, value: Any, *, sheet: str | None=None) -> str:
        ...

    async def close(self) -> None:
        ...
```

## `papilio.infra.excel.stream`

The [streaming guide](../guide/excel-streams.md) defines supported templates,
forward-only overlays, bounded batches, worker ownership and atomic publication.
The existing `ExcelWriter` retains its arbitrary-editing contract.

```python
class ExcelStreamWriter:
    def __init__(self, max_batch_rows: int = 250) -> None: ...

    @property
    def max_batch_rows(self) -> int: ...

    @asynccontextmanager
    async def open(
        self, output: str | Path, *, template: str | Path,
        repeat_style_row: int | Mapping[str, int] | None = 2,
    ) -> AsyncIterator[ExcelStreamSession]: ...

class ExcelStreamSession:
    @property
    def output(self) -> Path: ...

    @property
    def max_batch_rows(self) -> int: ...

    async def write_row(
        self, row: ExcelRow, *, sheet: str | None = None,
        start_row: int | None = None,
    ) -> None: ...

    async def write_rows(
        self, rows: Sequence[ExcelRow], *, sheet: str | None = None,
        start_row: int | None = None,
    ) -> None: ...

class ExcelStreamError(RuntimeError): ...
```

## `papilio.infra.files.reader`

### `FileReader`

```python
class FileReader:
    @asynccontextmanager
    async def open_text(self, path: str | PathLike[str], *, encoding: str='utf-8', errors: str='strict', newline: str | None=None) -> AsyncGenerator[AsyncFile[str]]:
        ...

    @asynccontextmanager
    async def open_bytes(self, path: str | PathLike[str]) -> AsyncGenerator[AsyncFile[bytes]]:
        ...

    async def read_text(self, path: str | PathLike[str], *, encoding: str='utf-8', errors: str='strict') -> str:
        ...

    async def read_bytes(self, path: str | PathLike[str]) -> bytes:
        ...
```

## `papilio.infra.files.writer`

### `FileWriter`

```python
class FileWriter:
    @asynccontextmanager
    async def open_text(self, path: str | PathLike[str], *, mode: Literal['w', 'a', 'x']='w', encoding: str='utf-8', errors: str='strict', newline: str | None=None) -> AsyncGenerator[AsyncFile[str]]:
        ...

    @asynccontextmanager
    async def open_bytes(self, path: str | PathLike[str], *, mode: Literal['wb', 'ab', 'xb']='wb') -> AsyncGenerator[AsyncFile[bytes]]:
        ...

    async def write_text(self, path: str | PathLike[str], data: str, *, mode: Literal['w', 'a', 'x']='w', encoding: str='utf-8') -> int:
        ...

    async def write_bytes(self, path: str | PathLike[str], data: bytes, *, mode: Literal['wb', 'ab', 'xb']='wb') -> int:
        ...
```
