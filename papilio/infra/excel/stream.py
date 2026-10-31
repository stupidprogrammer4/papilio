"""Independent, forward-only Excel streams with session-owned workers."""

import asyncio
import os
import shutil
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from multiprocessing import get_context
from multiprocessing.connection import Connection
from pathlib import Path
from tempfile import mkdtemp

from ._stream_workbook import (
    ExcelStreamError,
    WriteRow,
    WriteRows,
    stream_worker,
)
from .row import ExcelRow


def _receive(connection: Connection) -> None:
    try:
        answer = connection.recv()
    except (EOFError, OSError) as error:
        raise ExcelStreamError(
            "Excel stream worker closed unexpectedly"
        ) from error
    if isinstance(answer, Exception):
        raise answer


def _exchange(connection: Connection, command) -> None:
    connection.send(command)
    _receive(connection)


class ExcelStreamSession:
    """One workbook, one spawned worker and at most one in-flight batch."""

    def __init__(
        self,
        output: Path,
        template: Path,
        staging: Path,
        repeat_style_row: int | Mapping[str, int] | None,
        max_batch_rows: int,
    ) -> None:
        self._output = output
        self._staging = staging
        self._max_batch_rows = max_batch_rows
        self._closed = False
        self._lock = asyncio.Lock()
        context = get_context("spawn")
        self._connection, self._child = context.Pipe()
        try:
            self._process = context.Process(
                target=stream_worker,
                args=(
                    self._child,
                    str(template),
                    str(staging),
                    repeat_style_row,
                ),
                name="papilio-excel-stream",
            )
        except BaseException:
            self._connection.close()
            self._child.close()
            raise

    @property
    def output(self) -> Path:
        return self._output

    @property
    def max_batch_rows(self) -> int:
        return self._max_batch_rows

    async def _start(self) -> None:
        self._process.start()
        self._child.close()
        await asyncio.to_thread(_receive, self._connection)

    async def _request(self, command) -> None:
        if self._closed:
            raise ExcelStreamError("Excel stream session is closed")
        await asyncio.to_thread(_exchange, self._connection, command)

    async def write_row(
        self,
        row: ExcelRow,
        *,
        sheet: str | None = None,
        start_row: int | None = None,
    ) -> None:
        async with self._lock:
            await self._request(WriteRow(row, sheet, start_row))

    async def write_rows(
        self,
        rows: Sequence[ExcelRow],
        *,
        sheet: str | None = None,
        start_row: int | None = None,
    ) -> None:
        if len(rows) > self.max_batch_rows:
            raise ValueError("Excel stream batch exceeds max_batch_rows")
        async with self._lock:
            await self._request(WriteRows(rows, sheet, start_row))

    async def _finish(self) -> None:
        async with self._lock:
            await self._request("finish")
            await asyncio.to_thread(self._process.join)
            # This single local metadata operation is the publication point;
            # no await separates the final cancellation point from replacement.
            os.replace(self._staging / "workbook.xlsx", self.output)
            self._closed = True

    def _stop(self) -> None:
        self._closed = True
        self._connection.close()
        self._child.close()
        if self._process.pid is not None:
            if self._process.is_alive():
                self._process.terminate()
            self._process.join(timeout=5)
            if self._process.is_alive():
                self._process.kill()
                self._process.join()
        self._process.close()
        shutil.rmtree(self._staging)


class ExcelStreamWriter:
    """Write template overlays without retaining generated workbook cells.

    Use ``open`` once per output. Rows/classes must be spawn-pickleable.
    Each awaited write is bounded and acknowledged before another is sent.
    ``ExcelWriter`` remains the API for arbitrary workbook editing.
    """

    def __init__(self, max_batch_rows: int = 250) -> None:
        if (
            isinstance(max_batch_rows, bool)
            or not isinstance(max_batch_rows, int)
            or max_batch_rows < 1
        ):
            raise ValueError("max_batch_rows must be positive")
        self._max_batch_rows = max_batch_rows

    @property
    def max_batch_rows(self) -> int:
        return self._max_batch_rows

    @asynccontextmanager
    async def open(
        self,
        output: str | Path,
        *,
        template: str | Path,
        repeat_style_row: int | Mapping[str, int] | None = 2,
    ) -> AsyncIterator[ExcelStreamSession]:
        """Publish only on successful exit; aborts preserve existing output.

        Each sheet has its own forward-only row position. A supplied
        ``start_row`` may leave a forward gap, filled from the template.
        Existing template values in columns beyond the supplied row survive.
        New rows repeat the configured template style row; mapping entries
        select a style row per worksheet (missing entries disable repetition).
        """
        output, template = Path(output).absolute(), Path(template).absolute()
        if isinstance(repeat_style_row, Mapping):
            repeat_style_row = dict(repeat_style_row)
        # Creating the owned directory is a bounded metadata operation; it
        # must not complete in an abandoned executor after cancellation.
        staging = Path(mkdtemp(prefix=".papilio-excel-", dir=output.parent))
        session = None
        try:
            session = ExcelStreamSession(
                output,
                template,
                staging,
                repeat_style_row,
                self.max_batch_rows,
            )
            await session._start()
            yield session
            await session._finish()
        finally:
            if session is None:
                await asyncio.shield(asyncio.to_thread(shutil.rmtree, staging))
            else:
                await asyncio.shield(asyncio.to_thread(session._stop))
