# Async files, CSV and Excel

Each format has separate reader and writer tools. File and CSV operations use AnyIO worker threads for blocking I/O. `ExcelReader` and `ExcelWriter` jobs run in process pools. Async APIs keep blocking work off the event loop; they do not make a complete file operation atomic or install retry behavior.

## Text and binary files

Install `files`:

```python
from papilio.infra.files.reader import FileReader
from papilio.infra.files.writer import FileWriter

reader, writer = FileReader(), FileWriter()
characters = await writer.write_text("note.txt", "Hello Papilio")
text = await reader.read_text("note.txt")
bytes_written = await writer.write_bytes("payload.bin", b"payload")
payload = await reader.read_bytes("payload.bin")
```

Whole-file methods load the complete contents. For large files, open a stream:

```python
async with reader.open_bytes("source.bin") as source:
    async with writer.open_bytes("copy.bin", mode="xb") as target:
        while chunk := await source.read(1024 * 1024):
            await target.write(chunk)
```

The caller creates parent directories. Text modes are `w`, `a`, `x`; binary modes are `wb`, `ab`, `xb`. Write mode truncates, append extends, and exclusive creation fails when the file already exists. `write_text` returns characters; `write_bytes` returns bytes. Context managers close streams on normal exit or exceptions, including cancellation cleanup.

## CSV records

Install `csv`. This example writes records, then reads them incrementally:

```python
from papilio.infra.csv.reader import CSVReader
from papilio.infra.csv.writer import CSVWriter

async with CSVWriter().open("products.csv") as writer:
    count = await writer.write_rows([
        ["sku", "quantity"],
        ["BOOK", 2],
        ["PEN", 3],
    ])

async with CSVReader().rows("products.csv", batch_size=500) as rows:
    header = await anext(rows)
    async for sku, quantity in rows:
        print(sku, int(quantity))
```

Rows contain strings. Header handling, column validation and type conversion are explicit. For possibly empty files, use `anext(rows, None)`. The parser supports quoted delimiters and multiline fields; it does not split records by newline manually.

| Option | Meaning |
| --- | --- |
| `encoding` | Text encoding; use `utf-8-sig` when a BOM is required |
| `delimiter`, `quotechar`, `escapechar` | CSV syntax |
| `doublequote` | Escape a quote by doubling it |
| Reader `strict` | Reject malformed syntax; defaults to true |
| Reader `batch_size` | Number of parsed records fetched per worker batch |
| Writer `quoting`, `lineterminator` | CSV output policy |

`write_row` returns a character count. `write_rows` returns a **record count** and accepts a synchronous iterable. For an async producer, consume it in your coroutine and submit individual rows or bounded synchronous batches. Do not concurrently write through the same open CSV stream.

The [file pipeline example](../examples/index.md) filters a CSV without loading the whole input. Buffering is bounded by batch size and individual record size; a single huge record can still consume substantial memory.

## Typed Excel rows

Install `excel`:

```python
from papilio.infra.excel.row import ExcelRow, Row


class ProductRow(ExcelRow):
    sku: str = Row(title="SKU")
    quantity: int = Row(title="Quantity", ge=0)
```

Column order follows field declaration order. `Row` forwards field validation options to Pydantic. Titles are optional; field names are the fallback. Column metadata is prepared when the class is defined.

## Read and write workbooks

```python
from papilio.infra.excel.reader import ExcelReader
from papilio.infra.excel.writer import ExcelWriter

reader, writer = ExcelReader(max_workers=1), ExcelWriter(max_workers=1)
try:
    await writer.write_rows(
        "template.xlsx",
        "products.xlsx",
        [ProductRow(sku="BOOK", quantity=2)],
        start_row=1,
        with_titles=True,
    )
    rows = await reader.read_rows("products.xlsx", ProductRow, start_row=2)
finally:
    await reader.close()
    await writer.close()
```

The writer fills an existing `.xlsx` template. With titles enabled, data starts one row after `start_row`. Reader row numbers are one-based; it stops at the first completely empty row or the supplied limit. `read_rows` returns a list, not a stream. `read_cell` and `write_cell` address a cell such as `B3`; `sheet` selects a worksheet.

Use app-scoped providers for long-lived Excel tools, and close their process pools on shutdown. Standalone scripts must guard startup with `if __name__ == "__main__"` because workers use spawn. The [runnable Excel example](../examples/index.md) includes template creation and that guard.

Row validation and model construction run in the reader worker, which returns
the final models. The writer extracts titles and cell values in its worker.
Define row classes at module scope so workers can import them; local classes
inside functions are not supported. Row values and instances must be pickleable
for transfer between processes. Large transfers still carry serialization and
memory costs.

`read_cell` uses a read-only workbook to avoid loading all worksheet cells.
It scans up to the requested row, so cells near the end still require more
work. Formula cells return the workbook's cached result without recalculation.

## Stream large Excel exports

For sequential exports, use the independent
[`ExcelStreamWriter`](excel-streams.md). Each session owns one spawned worker
and a write-only workbook, accepts bounded `ExcelRow` batches, and publishes the
file atomically at successful context exit. Its template overlay supports a
limited set of workbook features; unsupported constructs fail explicitly. The
stateless stream writer needs no shutdown hook. See the
[streaming guide and runnable example](excel-streams.md) for its supported
formatting, forward-only positions and cancellation contract.

## Connect tools to an API

These classes do not require a framework-specific provider. Register stateless file/CSV tools directly with Dishka. Use a generator provider with cleanup for Excel, as shown in [dependency injection](application.md).

Choose upload limits, allowed paths and download responses in your HTTP layer. The low-level reader/writer does not interpret `storage` settings or install endpoints automatically.

[All file API signatures](../reference/files.md)
