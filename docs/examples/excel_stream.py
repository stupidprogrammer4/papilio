import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook, load_workbook

from papilio.infra.excel.row import ExcelRow
from papilio.infra.excel.stream import ExcelStreamWriter


class Item(ExcelRow):
    name: str
    quantity: int


def template(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "Items"
    sheet.append(["Name", "Quantity"])
    sheet.append([None, None])
    sheet["B2"].number_format = "#,##0"
    workbook.save(path)
    workbook.close()


async def main() -> None:
    with TemporaryDirectory() as folder:
        source, output = (
            Path(folder) / "template.xlsx",
            Path(folder) / "items.xlsx",
        )
        await asyncio.to_thread(template, source)
        async with ExcelStreamWriter(max_batch_rows=250).open(
            output,
            template=source,
        ) as session:
            await session.write_row(
                Item(name="First", quantity=2), start_row=2
            )
            await session.write_rows([Item(name="Second", quantity=3)])
        workbook = await asyncio.to_thread(
            load_workbook, output, read_only=True
        )
        try:
            sheet = workbook.active
            assert sheet is not None
            assert list(sheet.values) == [
                ("Name", "Quantity"),
                ("First", 2),
                ("Second", 3),
            ]
        finally:
            workbook.close()
        print("Excel: independent streaming workbook passed")


if __name__ == "__main__":
    asyncio.run(main())
