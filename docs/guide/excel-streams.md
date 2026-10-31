# Streaming Excel workbooks

Install `papilio[excel]` and use `ExcelStreamWriter` for large, sequential exports.
`ExcelWriter` remains available for arbitrary workbook editing.

```python
from papilio.infra.excel.stream import ExcelStreamWriter

writer = ExcelStreamWriter(max_batch_rows=250)
async with writer.open(
    "report.xlsx",
    template="template.xlsx",
    repeat_style_row={"Summary": 18, "Items": 2},
) as session:
    await session.write_rows(first_batch, sheet="Items", start_row=2)
    await session.write_rows(next_batch, sheet="Items")
    await session.write_rows(summary_rows, sheet="Summary", start_row=2)
```

Rows implement `ExcelRow`. Their classes must be importable at module scope and
rows must be pickleable, including their field values. `row.cells()` runs in a
session-owned spawned worker. IPC serialization runs in a thread; the event loop
does not convert cells, load templates, append worksheet data or save the archive.
Rows are processed in order. Each write waits for acknowledgement before another
batch can be sent. Batches larger than `max_batch_rows` raise `ValueError`; callers
must provide bounded batches. `write_row` writes one row independently.

Each worksheet has its own forward-only cursor, initially at row 1. `start_row`
is optional: omit it to continue from that cursor, or provide a forward position
to leave a gap. Gaps retain template content. Rewriting an emitted row raises
`ValueError` and aborts the session. A supplied row overlays its first N columns;
other template columns and trailing template rows remain. The template fixes tab
order, so the summary can be filled last and still appear first.

Template rows retain their own formatting. Generated rows beyond the template
repeat `repeat_style_row` (default 2), including blank styled columns. Pass `None`
to disable repetition, or a worksheet-name-to-row-number mapping for different
styles per worksheet. A missing mapping entry disables repetition for that sheet.
The selected style row must exist in that template. A blank template can use
`repeat_style_row=None`.

Supported template features include values, cell and dimension formats, fonts,
fills, borders, alignment, protection, RTL views, column widths, row dimensions,
freeze panes, filters, conditional formatting, data validation, print settings,
theme, workbook properties and defined names. This is a template overlay API,
not a general workbook roundtrip: merged cells, tables, formula cells, charts,
images/drawings, macros, external-workbook links, pivot tables/caches, slicers,
embedded objects, ActiveX, threaded comments, query tables/connections, custom XML
printer-specific settings and document signatures are rejected rather than silently discarded. Existing
filter/conditional-formatting ranges are preserved; configure export-wide ranges
in the template. Cell values retain normal openpyxl semantics, including generated
formulas; callers own appropriate escaping of untrusted spreadsheet content.

A stream creates one write-only workbook and saves it once. Its memory depends on
the template, worksheet/style metadata and current bounded batch, rather than all
generated cells. Worksheet XML and the completed archive use disk space in an
owned staging directory beside the output. Multiple sessions use independent
workers. `session.output` and `session.max_batch_rows` expose the destination and
batch limit; the stateless writer needs no application shutdown hook.

With Dishka, register an explicit factory so the batch limit remains
configuration rather than an `int` dependency:

```python
from dishka import Provider, Scope, provide
from papilio.infra.excel.stream import ExcelStreamWriter


class ExportTools(Provider):
    @provide(scope=Scope.APP)
    def excel_stream(self) -> ExcelStreamWriter:
        return ExcelStreamWriter(max_batch_rows=250)
```

Successful context exit atomically replaces the destination. A body exception,
conversion failure, worker crash or cancellation before publication preserves an
existing destination and removes owned workers and staging files. Atomic rename
is the publication point; no partial workbook is exposed. The local directory
creation and final rename are bounded metadata operations on the event loop.
Do not share one destination between simultaneous sessions.

Run the standalone native example with:

```bash
python docs/examples/excel_stream.py
```
