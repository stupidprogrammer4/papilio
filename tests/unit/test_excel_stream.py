import asyncio
import os
import time
from copy import copy
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from decimal import Decimal
from multiprocessing import active_children
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.cell.rich_text import CellRichText
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.table import Table
from pydantic import PrivateAttr

from papilio.infra.excel.row import ExcelRow
from papilio.infra.excel.stream import ExcelStreamError, ExcelStreamWriter


class Values(ExcelRow):
    values: tuple[Any, ...]
    _origin: int = PrivateAttr(default_factory=os.getpid)

    def cells(self) -> list[Any]:
        assert os.getpid() != self._origin
        return list(self.values)


class ProcessRow(ExcelRow):
    value: str

    def cells(self) -> list[Any]:
        return [self.value, os.getpid()]


class InvalidRow(ExcelRow):
    def cells(self) -> list[Any]:
        raise ValueError("native cells failure")


class CrashingRow(ExcelRow):
    def cells(self) -> list[Any]:
        os._exit(17)


class SleepingRow(ExcelRow):
    marker: str

    def cells(self) -> list[Any]:
        Path(self.marker).write_text(str(os.getpid()))
        time.sleep(30)
        return ["late"]


def make_template(path: Path) -> None:
    workbook = Workbook()
    summary = workbook.active
    assert summary is not None
    summary.title = "Summary"
    summary.append(["Label", "Amount", "Preserved"])
    summary.append(["placeholder", 0, "legend"])
    summary.append(["gap", None, "gap legend"])
    summary.append([None, None, "fourth legend"])
    summary.append(["tail", 8])
    summary["B2"].number_format = "#,##0"
    summary["D3"] = "=1+2"
    summary["D3"].data_type = "s"
    summary["D2"] = "#DIV/0!"
    summary["D2"].data_type = "s"
    summary["B4"].number_format = "0.000"
    data = workbook.create_sheet("Data")
    workbook.defined_names.add(
        DefinedName("GlobalRange", attr_text="'Data'!$A$1")
    )
    data.defined_names.add(
        DefinedName("LocalRange", attr_text="'Data'!$B$2", localSheetId=1)
    )
    data.append(["Name", "Count", "Date"])
    data.append([None, None, None])
    data.sheet_view.rightToLeft = True
    data.freeze_panes = "B2"
    data.auto_filter.ref = "A1:C1048576"
    data.column_dimensions["A"].width = 27
    data.column_dimensions["B"].number_format = "0.00"
    data.column_dimensions["B"].font = Font(name="Arial", bold=True)
    data.row_dimensions[2].height = 22
    data.row_dimensions[2].number_format = "#,##0"
    data["A2"].alignment = Alignment(readingOrder=2, horizontal="right")
    data["A2"].font = Font(name="Arial", color="112233", bold=True)
    data["B2"].number_format = "#,##0"
    data["C2"].number_format = "yyyy-mm-dd hh:mm:ss"
    data.conditional_formatting.add(
        "B2:B1048576",
        CellIsRule(
            operator="lessThan",
            formula=["0"],
            fill=PatternFill("solid", fgColor="FF0000"),
        ),
    )
    workbook.save(path)
    workbook.close()


@pytest.fixture
def template(tmp_path):
    path = tmp_path / "template.xlsx"
    make_template(path)
    return path


def assert_clean(tmp_path, baseline):
    assert list(tmp_path.glob(".papilio-excel-*")) == []
    assert {child.pid for child in active_children()} == baseline


async def test_stream_overlay_order_styles_worker_conversion_and_atomic_output(
    template, tmp_path
):
    output = tmp_path / "output.xlsx"
    output.write_bytes(b"existing output")
    writer = ExcelStreamWriter(max_batch_rows=2)
    baseline = {child.pid for child in active_children()}
    async with writer.open(output, template=template) as session:
        assert session.output == output
        assert session.max_batch_rows == writer.max_batch_rows == 2
        await session.write_row(
            Values(values=("first", 2)), sheet="Data", start_row=2
        )
        await session.write_rows(
            [
                Values(values=("second", 3, datetime(2026, 10, 31))),
                Values(values=("third", 4)),
            ],
            sheet="Data",
        )
        await session.write_row(
            Values(values=("total", 9)), sheet="Summary", start_row=2
        )
        await session.write_row(
            Values(values=("later", 8)), sheet="Summary", start_row=4
        )
        assert output.read_bytes() == b"existing output"
    workbook = load_workbook(output)
    source = load_workbook(template)
    try:
        assert workbook.sheetnames == ["Summary", "Data"]
        summary, data = workbook.worksheets
        assert workbook.defined_names["GlobalRange"].attr_text == "'Data'!$A$1"
        assert data.defined_names["LocalRange"].attr_text == "'Data'!$B$2"
        assert summary["A2"].value == "total"
        assert summary["C2"].value == "legend"
        assert summary["D2"].value == "#DIV/0!"
        assert summary["D2"].data_type == "s"
        assert summary["D3"].value == "=1+2"
        assert summary["D3"].data_type == "s"
        assert summary["A3"].value == "gap"
        assert summary["C4"].value == "fourth legend"
        assert summary["A5"].value == "tail"
        assert [data.cell(n, 1).value for n in range(2, 5)] == [
            "first",
            "second",
            "third",
        ]
        assert data["C3"].value == datetime(2026, 10, 31)
        assert data["C4"].number_format == source["Data"]["C2"].number_format
        assert data["B4"].number_format == "#,##0"
        assert copy(data["A4"].font) == copy(source["Data"]["A2"].font)
        assert copy(data["A4"].alignment) == copy(
            source["Data"]["A2"].alignment
        )
        assert data.row_dimensions[4].height == 22
        assert data.row_dimensions[4].number_format == "#,##0"
        assert copy(data.column_dimensions["B"].font) == copy(
            source["Data"].column_dimensions["B"].font
        )
        assert data.column_dimensions["B"].number_format == "0.00"
        assert data.column_dimensions["A"].width == 27
        assert data.sheet_view.rightToLeft is True
        assert data.views == source["Data"].views
        assert data.freeze_panes == "B2"
        assert data.auto_filter.ref == "A1:C1048576"
        assert list(data.conditional_formatting) == list(
            source["Data"].conditional_formatting
        )
    finally:
        workbook.close()
        source.close()
    assert_clean(tmp_path, baseline)


async def test_stream_temporal_values_keep_each_repeated_style_independent(
    template, tmp_path
):
    source = load_workbook(template)
    source["Data"]["A2"].number_format = "General"
    source.save(template)
    source.close()
    output = tmp_path / "temporal.xlsx"
    values = (
        date(2026, 10, 31),
        datetime(2026, 10, 31, 12, 30),
        datetime_time(12, 30),
        timedelta(hours=12),
        42,
    )
    async with ExcelStreamWriter().open(output, template=template) as session:
        await session.write_rows(
            [Values(values=(value,)) for value in values],
            sheet="Data",
            start_row=2,
        )
    workbook = load_workbook(output)
    try:
        cells = [workbook["Data"].cell(row, 1) for row in range(2, 7)]
        assert [cell.number_format for cell in cells] == ["General"] * 5
        assert all(isinstance(cell.value, (int, float)) for cell in cells)
        assert cells[-1].value == 42
        assert all(
            copy(cell.alignment) == copy(cells[0].alignment) for cell in cells
        )
    finally:
        workbook.close()


async def test_stream_repeated_scalar_cells_preserve_values_across_batches(
    template, tmp_path
):
    output = tmp_path / "scalar-batches.xlsx"
    values = (
        "template overlay",
        12,
        Decimal("12.345"),
        CellRichText(["=1+2"]),
        None,
        datetime(2026, 10, 31, 12, 30),
        42,
        False,
        "=2+3",
        "آخرین مقدار",
    )
    async with ExcelStreamWriter(max_batch_rows=2).open(
        output, template=template
    ) as session:
        for offset in range(0, len(values), 2):
            await session.write_rows(
                [
                    Values(values=(value,))
                    for value in values[offset : offset + 2]
                ],
                sheet="Data",
                start_row=offset + 2,
            )
    workbook = load_workbook(output)
    source = load_workbook(template)
    try:
        sheet = workbook["Data"]
        assert [sheet.cell(row, 1).value for row in (2, 3, 4, 5, 6)] == [
            "template overlay",
            12,
            12.345,
            "=1+2",
            None,
        ]
        assert sheet["A5"].data_type == "s"
        assert isinstance(sheet["A7"].value, (int, float))
        assert sheet["A8"].value == 42
        assert sheet["A9"].value is False
        assert sheet["A10"].value == "=2+3"
        assert sheet["A10"].data_type == "f"
        assert sheet["A11"].value == "آخرین مقدار"
        assert sheet["A11"].data_type == "s"
        for row in range(2, 12):
            cell = sheet.cell(row, 1)
            assert cell.number_format == "General"
            assert copy(cell.alignment) == copy(source["Data"]["A2"].alignment)
            assert sheet.cell(row, 2).number_format == "#,##0"
    finally:
        workbook.close()
        source.close()


async def test_stream_per_sheet_repeat_rows_and_forward_gap(
    template, tmp_path
):
    output = tmp_path / "repeat.xlsx"
    async with ExcelStreamWriter().open(
        output,
        template=template,
        repeat_style_row={"Summary": 4, "Data": 2},
    ) as session:
        await session.write_rows(
            [Values(values=("one", 2))], sheet="Summary", start_row=6
        )
        await session.write_row(
            Values(values=("two", 3)), sheet="Data", start_row=2
        )
    workbook = load_workbook(output)
    try:
        assert workbook["Summary"]["B6"].number_format == "0.000"
        assert workbook["Summary"]["A5"].value == "tail"
        assert workbook["Data"]["B2"].number_format == "#,##0"
    finally:
        workbook.close()


@pytest.mark.parametrize(
    "feature", ["merged", "table", "formula", "drawing", "macro", "external"]
)
async def test_unsupported_templates_fail_without_replacing_output(
    template, tmp_path, feature
):
    if feature in {"merged", "table", "formula"}:
        workbook = load_workbook(template)
        sheet = workbook["Data"]
        if feature == "merged":
            sheet.merge_cells("A1:B1")
        elif feature == "table":
            sheet.add_table(Table(displayName="Items", ref="A1:C2"))
        else:
            sheet["A2"] = "=1+2"
        workbook.save(template)
        workbook.close()
    else:
        part = {
            "drawing": "xl/drawings/drawing1.xml",
            "macro": "xl/vbaProject.bin",
            "external": "xl/externalLinks/externalLink1.xml",
        }[feature]
        with ZipFile(template, "a") as archive:
            archive.writestr(part, "unsupported")
    output = tmp_path / "old.xlsx"
    output.write_bytes(b"old")
    baseline = {child.pid for child in active_children()}
    with pytest.raises(ValueError):
        async with ExcelStreamWriter().open(output, template=template):
            pytest.fail("unsupported template was accepted")
    assert output.read_bytes() == b"old"
    assert_clean(tmp_path, baseline)


@pytest.mark.parametrize("row", [InvalidRow(), CrashingRow()])
async def test_native_worker_error_or_crash_aborts_cleanly(
    template, tmp_path, row
):
    baseline = {child.pid for child in active_children()}
    output = tmp_path / "old.xlsx"
    output.write_bytes(b"old")
    with pytest.raises((ValueError, ExcelStreamError)):
        async with ExcelStreamWriter().open(
            output, template=template
        ) as session:
            await session.write_row(row, sheet="Data", start_row=2)
    assert output.read_bytes() == b"old"
    assert_clean(tmp_path, baseline)


async def test_body_abort_and_write_cancellation_preserve_existing_file(
    template, tmp_path
):
    baseline = {child.pid for child in active_children()}
    output = tmp_path / "old.xlsx"
    output.write_bytes(b"old")
    with pytest.raises(RuntimeError, match="consumer abort"):
        async with ExcelStreamWriter().open(
            output, template=template
        ) as session:
            await session.write_row(
                Values(values=("early",)), sheet="Data", start_row=2
            )
            raise RuntimeError("consumer abort")
    assert output.read_bytes() == b"old"
    assert_clean(tmp_path, baseline)
    marker = tmp_path / "worker-started"

    async def consume():
        async with ExcelStreamWriter().open(
            output, template=template
        ) as session:
            await session.write_row(
                SleepingRow(marker=str(marker)), sheet="Data", start_row=2
            )

    task = asyncio.create_task(consume())
    async with asyncio.timeout(10):
        while not marker.exists():
            await asyncio.sleep(0.01)
    assert int(marker.read_text()) != os.getpid()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert output.read_bytes() == b"old"
    assert_clean(tmp_path, baseline)


async def test_startup_cancellation_cleans_worker_and_staging(
    template, tmp_path
):
    baseline = {child.pid for child in active_children()}
    output = tmp_path / "cancel.xlsx"
    entered = asyncio.Event()

    async def consume():
        async with ExcelStreamWriter().open(output, template=template):
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(consume())
    async with asyncio.timeout(10):
        while {child.pid for child in active_children()} == baseline:
            await asyncio.sleep(0)
    assert not entered.is_set()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not output.exists()
    assert_clean(tmp_path, baseline)


async def test_independent_concurrent_sessions_use_distinct_workers(
    template, tmp_path
):
    writer = ExcelStreamWriter()
    baseline = {child.pid for child in active_children()}

    async def create(name):
        output = tmp_path / f"{name}.xlsx"
        async with writer.open(output, template=template) as session:
            await session.write_row(
                ProcessRow(value=name), sheet="Data", start_row=2
            )
            await session.write_row(ProcessRow(value=name), sheet="Data")
        workbook = load_workbook(output)
        try:
            assert workbook["Data"]["A2"].value == name
            pid = workbook["Data"]["B2"].value
            assert pid == workbook["Data"]["B3"].value
            assert pid != os.getpid()
            return pid
        finally:
            workbook.close()

    first, second = await asyncio.gather(create("first"), create("second"))
    assert first != second
    assert_clean(tmp_path, baseline)


@pytest.mark.parametrize("bound", [0, -1, True, 1.5, "250"])
async def test_batch_bound_requires_positive_integer(bound):
    with pytest.raises(ValueError):
        ExcelStreamWriter(max_batch_rows=bound)


@pytest.mark.parametrize("position", [0, -1, True, 1.5])
async def test_row_position_rejects_invalid_values(
    template, tmp_path, position
):
    with pytest.raises(ValueError):
        async with ExcelStreamWriter().open(
            tmp_path / "bad.xlsx", template=template
        ) as session:
            await session.write_row(
                Values(values=("bad",)), sheet="Data", start_row=position
            )
    assert list(tmp_path.glob(".papilio-excel-*")) == []


async def test_batch_capacity_columns_and_backward_positions(
    template, tmp_path
):
    with pytest.raises(ValueError, match="max_batch_rows"):
        async with ExcelStreamWriter(max_batch_rows=1).open(
            tmp_path / "large.xlsx", template=template
        ) as session:
            await session.write_rows(
                [Values(values=(1,)), Values(values=(2,))], sheet="Data"
            )
    with pytest.raises(ValueError, match="forward"):
        async with ExcelStreamWriter().open(
            tmp_path / "backward.xlsx", template=template
        ) as session:
            await session.write_row(
                Values(values=(1,)), sheet="Data", start_row=2
            )
            await session.write_row(
                Values(values=(2,)), sheet="Data", start_row=2
            )
    with pytest.raises(ValueError, match="column capacity"):
        async with ExcelStreamWriter().open(
            tmp_path / "wide.xlsx", template=template
        ) as session:
            await session.write_row(
                Values(values=(None,) * 16_385), sheet="Data", start_row=2
            )
    assert list(tmp_path.glob(".papilio-excel-*")) == []
