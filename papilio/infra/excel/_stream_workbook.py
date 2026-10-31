"""Worker-owned write-only workbook and bounded template overlay."""

import tempfile
from collections.abc import Mapping, Sequence
from copy import copy, deepcopy
from dataclasses import dataclass
from datetime import date, time, timedelta
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, cast
from zipfile import ZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.cell import Cell
from openpyxl.styles import Alignment, Border, Font, NamedStyle, Protection
from openpyxl.styles.fills import Fill
from openpyxl.worksheet.worksheet import Worksheet

from .row import ExcelRow


@dataclass(frozen=True)
class WriteRow:
    row: ExcelRow
    sheet: str | None
    start_row: int | None


@dataclass(frozen=True)
class WriteRows:
    rows: Sequence[ExcelRow]
    sheet: str | None
    start_row: int | None


class ExcelStreamError(RuntimeError):
    """The stream worker stopped without a successful response."""


_STYLE_PARTS = (
    "font",
    "fill",
    "border",
    "alignment",
    "protection",
    "number_format",
    "quotePrefix",
    "pivotButton",
)


def copy_dimension(source, parent):
    dimension = copy(source)
    dimension.parent = parent
    if source.has_style:
        for name in _STYLE_PARTS:
            setattr(dimension, name, copy(getattr(source, name)))
    return dimension


class StreamWorksheet:
    def __init__(self, source, target, styles, repeat_style_row):
        self.source = source
        self.target = target
        self.styles = styles
        self.repeat_style_row = repeat_style_row
        self.next_row = 1
        self.max_template_row = source.max_row
        self.max_column = source.max_column
        self.last_template_row = max(
            self.max_template_row, max(source.row_dimensions, default=0)
        )
        self.repeat_styles = ()
        if repeat_style_row is not None:
            repeat_cells = next(
                source.iter_rows(
                    min_row=repeat_style_row,
                    max_row=repeat_style_row,
                    max_col=self.max_column,
                )
            )
            self.repeat_styles = self.row_styles(repeat_cells)
        self.repeat_cells = tuple(
            Cell(
                target,
                row=1,
                column=1,
                style_array=style[0] if style is not None else None,
            )
            for style in self.repeat_styles
        )

    def row_styles(self, cells):
        return tuple(
            self.styles[cell.style_id] if cell.has_style else None
            for cell in cells
        )

    def append(self, values: list[Any] | None = None) -> None:
        row = self.next_row
        if row > 1_048_576:
            raise ValueError("Excel worksheet row capacity exceeded")
        existing = (
            list(self.source.iter_rows(min_row=row, max_row=row))[0]
            if row <= self.max_template_row
            else ()
        )
        row_styles = self.row_styles(existing)
        if not existing and values is not None and self.repeat_style_row:
            row_styles = self.repeat_styles
        size = max(
            len(existing),
            len(row_styles),
            len(values) if values is not None else 0,
        )
        if size > 16_384:
            raise ValueError("Excel worksheet column capacity exceeded")
        cells = []
        for index in range(size):
            value = existing[index].value if index < len(existing) else None
            if values is not None and index < len(values):
                value = values[index]
            style = row_styles[index] if index < len(row_styles) else None
            temporal = isinstance(value, (date, time, timedelta))
            if (
                not existing
                and values is not None
                and index < len(self.repeat_cells)
                and not temporal
            ):
                # Native append consumes cells synchronously. Scalar binding
                # leaves their registered styles unchanged between rows.
                cell = self.repeat_cells[index]
                cell.value = value
            else:
                # Temporal binding can change number formats, so it needs an
                # independent style array even on generated rows.
                cell = Cell(
                    self.target,
                    row=1,
                    column=1,
                    value=value,
                    style_array=style[0] if style is not None else None,
                )
            if style is not None and temporal:
                # Preserve template formatting after native temporal binding,
                # just as assigning a template style after setting the value.
                cell.number_format = style[1]
            if index < len(existing) and (
                values is None or index >= len(values)
            ):
                cell.data_type = existing[index].data_type
            if index < len(existing):
                original = existing[index]
                if original.comment is not None:
                    cell.comment = copy(original.comment)
                if original.hyperlink is not None:
                    cell.hyperlink = copy(original.hyperlink)
            cells.append(cell)
        dimension = self.source.row_dimensions.get(row)
        if dimension is None and values is not None and self.repeat_style_row:
            dimension = self.source.row_dimensions.get(self.repeat_style_row)
        if dimension is not None:
            copied = copy_dimension(dimension, self.target)
            copied.index = row
            self.target.row_dimensions[row] = copied
        self.target.append(cells)
        # Write-only XML already contains this dimension; do not retain a
        # per-output-row dimension object in memory.
        if row in self.target.row_dimensions:
            del self.target.row_dimensions[row]
        self.next_row += 1

    def position(self, start_row: int | None) -> None:
        if start_row is None:
            return
        if (
            isinstance(start_row, bool)
            or not isinstance(start_row, int)
            or start_row < self.next_row
        ):
            raise ValueError(
                "start_row must move forward within the worksheet"
            )
        if start_row > 1_048_576:
            raise ValueError("start_row exceeds Excel worksheet capacity")
        while self.next_row < start_row:
            self.append()

    def finish(self) -> None:
        while self.next_row <= self.last_template_row:
            self.append()


class StreamWorkbook:
    def __init__(self, template: str, repeat_style_row):
        self._validate_parts(template)
        self.source = load_workbook(template)
        self.target = Workbook(write_only=True)
        try:
            self._prepare(repeat_style_row)
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _validate_parts(template: str) -> None:
        unsupported = (
            "xl/charts/",
            "xl/media/",
            "xl/printerSettings/",
            "xl/drawings/",
            "xl/tables/",
            "xl/pivotTables/",
            "xl/pivotCache/",
            "xl/externalLinks/",
            "xl/embeddings/",
            "xl/activeX/",
            "xl/slicers/",
            "xl/slicerCaches/",
            "xl/threadedComments/",
            "xl/persons/",
            "customXml/",
            "xl/queryTables/",
            "_xmlsignatures/",
        )
        with ZipFile(template) as archive:
            for name in archive.namelist():
                if name.startswith(unsupported) or name in {
                    "xl/vbaProject.bin",
                    "xl/connections.xml",
                }:
                    raise ValueError(
                        f"Unsupported streaming template part: {name}"
                    )

    def _prepare(self, repeat_style_row) -> None:
        source, target = self.source, self.target
        if source.chartsheets:
            raise ValueError("Chart sheets are not supported for streaming")
        target.properties = deepcopy(source.properties)
        # openpyxl-stubs omits this public workbook attribute.
        target.custom_doc_props = deepcopy(source.custom_doc_props)  # type: ignore[attr-defined]
        target.security = deepcopy(source.security)
        target.calculation = deepcopy(source.calculation)
        target.views = deepcopy(source.views)
        target.loaded_theme = source.loaded_theme
        target.epoch = source.epoch
        target.defined_names = deepcopy(source.defined_names)
        styles = {}
        self.sheets = {}
        if isinstance(repeat_style_row, Mapping):
            unknown = set(repeat_style_row) - set(source.sheetnames)
            if unknown:
                raise ValueError(
                    f"Unknown repeat-style worksheets: {sorted(unknown)}"
                )
        for sheet in source:
            if not isinstance(sheet, Worksheet):
                raise ValueError("Only worksheets are supported for streaming")
            if sheet.merged_cells.ranges or sheet.tables:
                raise ValueError("Merged cells and tables require ExcelWriter")
            for row in sheet:
                for cell in row:
                    if cell.data_type == "f":
                        raise ValueError(
                            "Template formulas require ExcelWriter"
                        )
                    if cell.has_style and cell.style_id not in styles:
                        style = NamedStyle(
                            name=f"stream_{cell.style_id}",
                            font=cast(Font, copy(cell.font)),
                            fill=cast(Fill, copy(cell.fill)),
                            border=cast(Border, copy(cell.border)),
                            alignment=cast(Alignment, copy(cell.alignment)),
                            protection=cast(Protection, copy(cell.protection)),
                            number_format=cell.number_format,
                        )
                        target.add_named_style(style)
                        array = copy(style.as_tuple())
                        array.quotePrefix = cell.quotePrefix
                        array.pivotButton = cell.pivotButton
                        styles[cell.style_id] = (array, style.number_format)
            output = target.create_sheet(sheet.title)
            output.sheet_state = sheet.sheet_state
            output.sheet_properties = deepcopy(sheet.sheet_properties)
            output.defined_names = deepcopy(sheet.defined_names)
            output.sheet_format = deepcopy(sheet.sheet_format)
            output.views = deepcopy(sheet.views)
            output.auto_filter = deepcopy(sheet.auto_filter)
            output.conditional_formatting = deepcopy(
                sheet.conditional_formatting
            )
            output.data_validations = deepcopy(sheet.data_validations)
            output.protection = deepcopy(sheet.protection)
            output.print_options = deepcopy(sheet.print_options)
            output.page_margins = deepcopy(sheet.page_margins)
            output.page_setup = deepcopy(sheet.page_setup)
            output.HeaderFooter = deepcopy(sheet.HeaderFooter)
            output.print_title_rows = sheet.print_title_rows
            output.print_title_cols = sheet.print_title_cols
            output.print_area = sheet.print_area
            output.row_breaks = deepcopy(sheet.row_breaks)
            output.col_breaks = deepcopy(sheet.col_breaks)
            for key, dimension in sheet.column_dimensions.items():
                output.column_dimensions[key] = copy_dimension(
                    dimension, output
                )
            repeat = (
                repeat_style_row.get(sheet.title)
                if isinstance(repeat_style_row, Mapping)
                else repeat_style_row
            )
            if repeat is not None and (
                isinstance(repeat, bool)
                or not isinstance(repeat, int)
                or not 1 <= repeat <= sheet.max_row
            ):
                raise ValueError(
                    "repeat_style_row must identify a template row"
                )
            self.sheets[sheet.title] = StreamWorksheet(
                sheet, output, styles, repeat
            )
        active = source.active
        self.default_sheet = (
            active.title if active is not None else source.sheetnames[0]
        )
        target.active = source.sheetnames.index(self.default_sheet)

    def worksheet(self, sheet: str | None) -> StreamWorksheet:
        return self.sheets[sheet or self.default_sheet]

    def write_row(self, command: WriteRow) -> None:
        sheet = self.worksheet(command.sheet)
        sheet.position(command.start_row)
        sheet.append(command.row.cells())

    def write_rows(self, command: WriteRows) -> None:
        sheet = self.worksheet(command.sheet)
        sheet.position(command.start_row)
        for row in command.rows:
            sheet.append(row.cells())

    def save(self, output: Path) -> None:
        for sheet in self.sheets.values():
            sheet.finish()
        self.target.save(output)

    def close(self) -> None:
        for sheet in self.target:
            if not sheet.closed:
                sheet.close()
        self.source.close()
        self.target.close()


def stream_worker(
    connection: Connection,
    template: str,
    staging: str,
    repeat_style_row,
) -> None:
    # openpyxl's worksheet XML temporary files must share this session's
    # directory so the parent can clean them even after worker termination.
    tempfile.tempdir = staging
    workbook = None
    try:
        workbook = StreamWorkbook(template, repeat_style_row)
        connection.send(None)
        while True:
            command = connection.recv()
            if command == "finish":
                workbook.save(Path(staging) / "workbook.xlsx")
                connection.send(None)
                break
            if isinstance(command, WriteRow):
                workbook.write_row(command)
            elif isinstance(command, WriteRows):
                workbook.write_rows(command)
            else:
                raise ValueError("Unknown Excel stream command")
            connection.send(None)
    except EOFError:
        pass
    except Exception as error:
        try:
            connection.send(error)
        except Exception:
            connection.send(
                ExcelStreamError(f"{type(error).__name__}: {error}")
            )
    finally:
        if workbook is not None:
            workbook.close()
        connection.close()
