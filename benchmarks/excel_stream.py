"""Compare equivalent template exports in a fresh process per invocation.

Run from the repository root, supplying a real report template and detail tab:
  python benchmarks/excel_stream.py --mode stream --rows 10000 \
      --template orders.xlsx --sheet items
Repeat with --mode template. Linux ru_maxrss measures the completed worker's
peak RSS, not the parent's memory. This local workload is not a production SLA.
"""

import argparse
import asyncio
import hashlib
import json
import resource
import tempfile
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from xml.etree.ElementTree import iterparse
from zipfile import ZipFile

from openpyxl import load_workbook

from papilio.infra.excel.row import ExcelRow
from papilio.infra.excel.stream import ExcelStreamWriter
from papilio.infra.excel.writer import ExcelWriter


class ExportRow(ExcelRow):
    index: int
    width: int

    def cells(self) -> list:
        values = (self.index, f"order-{self.index}", Decimal("12.345"))
        return [values[column % 3] for column in range(self.width)]


class ExportRows(Sequence[ExportRow]):
    def __init__(self, count: int, width: int) -> None:
        self.count = count
        self.width = width

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index):
        if isinstance(index, slice):
            raise TypeError("benchmark rows are not materialized")
        if index < 0 or index >= self.count:
            raise IndexError(index)
        return ExportRow(index=index + 1, width=self.width)


async def run(args) -> None:
    template = load_workbook(args.template, read_only=True)
    width = template[args.sheet].max_column
    sheet_number = template.sheetnames.index(args.sheet) + 1
    template.close()
    assert width is not None
    loop = asyncio.get_running_loop()
    delays = []
    expected = loop.time() + 0.02

    def tick():
        nonlocal expected, heartbeat
        delays.append(max(0, loop.time() - expected))
        expected = loop.time() + 0.02
        heartbeat = loop.call_at(expected, tick)

    heartbeat = loop.call_at(expected, tick)
    with tempfile.TemporaryDirectory(
        prefix="papilio-excel-benchmark-"
    ) as directory:
        output = Path(directory) / "export.xlsx"
        batch_rows = None
        started = perf_counter()
        try:
            if args.mode == "template":
                writer = ExcelWriter()
                try:
                    await writer.write_rows(
                        args.template,
                        str(output),
                        ExportRows(args.rows, width),
                        sheet=args.sheet,
                        start_row=2,
                    )
                finally:
                    await writer.close()
            else:
                stream_writer = ExcelStreamWriter()
                batch_rows = stream_writer.max_batch_rows
                async with stream_writer.open(
                    output, template=args.template
                ) as session:
                    for offset in range(
                        0, args.rows, stream_writer.max_batch_rows
                    ):
                        await session.write_rows(
                            tuple(
                                ExportRow(index=index + 1, width=width)
                                for index in range(
                                    offset,
                                    min(
                                        offset + stream_writer.max_batch_rows,
                                        args.rows,
                                    ),
                                )
                            ),
                            sheet=args.sheet,
                            start_row=offset + 2,
                        )
            elapsed = perf_counter() - started
        finally:
            heartbeat.cancel()
        peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss / 1024
        digest = hashlib.sha256()
        found = 0
        namespace = (
            "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        )
        # Compare stored values directly: the stream deliberately propagates
        # template number formats beyond row 2, unlike the editing writer.
        with (
            ZipFile(output) as archive,
            archive.open(f"xl/worksheets/sheet{sheet_number}.xml") as stream,
        ):
            for _, element in iterparse(stream, events=("end",)):
                if element.tag != namespace + "row":
                    continue
                if int(element.attrib["r"]) == 1:
                    element.clear()
                    continue
                found += 1
                values = tuple("".join(cell.itertext()) for cell in element)
                assert len(values) == width
                assert values[:3] == (str(found), f"order-{found}", "12.345")
                digest.update(repr(values).encode())
                element.clear()
        assert found == args.rows
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "rows": args.rows,
                    "columns": width,
                    "batch_rows": batch_rows,
                    "seconds": round(elapsed, 3),
                    "worker_peak_mib": round(peak, 1),
                    "max_loop_delay_ms": round(
                        max(delays, default=0) * 1000, 1
                    ),
                    "detail_sha256": digest.hexdigest(),
                }
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("template", "stream"), required=True
    )
    parser.add_argument("--rows", type=int, required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--sheet", required=True)
    asyncio.run(run(parser.parse_args()))
