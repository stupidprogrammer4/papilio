import csv
import threading

import pytest

from papilio.infra.csv.reader import CSVReader
from papilio.infra.csv.writer import CSVWriter
from papilio.infra.files.reader import FileReader
from papilio.infra.files.writer import FileWriter


async def test_text_binary_append_and_exclusive_creation(tmp_path):
    reader, writer = FileReader(), FileWriter()
    text = tmp_path / "text.txt"
    assert await writer.write_text(text, "پروانه\n") == 7
    await writer.write_text(text, "tail", mode="a")
    assert await reader.read_text(text) == "پروانه\ntail"
    with pytest.raises(FileExistsError):
        await writer.write_text(text, "overwrite", mode="x")
    assert await reader.read_text(text) == "پروانه\ntail"
    raw = tmp_path / "raw.bin"
    assert await writer.write_bytes(raw, b"\x00\xff") == 2
    await writer.write_bytes(raw, b"\x01", mode="ab")
    assert await reader.read_bytes(raw) == b"\x00\xff\x01"


async def test_file_contexts_close_on_error_and_allow_incremental_reads(
    tmp_path,
):
    path = tmp_path / "stream.txt"
    with pytest.raises(RuntimeError):
        async with FileWriter().open_text(path) as stream:
            await stream.write("first\nsecond\n")
            raise RuntimeError("stop")
    assert stream.wrapped.closed
    async with FileReader().open_text(path) as source:
        assert await source.readline() == "first\n"
        assert await source.readline() == "second\n"
    assert source.wrapped.closed


@pytest.mark.parametrize("size", [1, 2, 1000])
async def test_csv_multiline_unicode_quotes_and_batch_boundaries(
    tmp_path, size
):
    path = tmp_path / "rows.csv"
    rows = [["name", "notes"], ["پروانه", 'a;"b"\r\nc'], ["", "tail"], []]
    async with CSVWriter().open(path, delimiter=";") as writer:
        assert await writer.write_row(rows[0]) > 0
        assert await writer.write_rows(rows[1:]) == 3
    async with CSVReader().rows(
        path, delimiter=";", batch_size=size
    ) as records:
        assert [row async for row in records] == rows


async def test_csv_empty_append_and_bad_format(tmp_path):
    path = tmp_path / "empty.csv"
    async with CSVWriter().open(path) as writer:
        assert await writer.write_rows([]) == 0
    async with CSVReader().rows(path) as records:
        assert [row async for row in records] == []
    async with CSVWriter().open(path, mode="a") as writer:
        await writer.write_row(["appended", "value"])
    async with CSVReader().rows(path) as records:
        assert [row async for row in records] == [["appended", "value"]]
    path.write_text('"unterminated\n')
    with pytest.raises(csv.Error):
        async with CSVReader().rows(path) as records:
            _ = [row async for row in records]


async def test_csv_batch_consumption_runs_off_the_event_loop(tmp_path):
    event_thread = threading.get_ident()

    def rows():
        assert threading.get_ident() != event_thread
        for index in range(5000):
            yield [index, "value"]

    path = tmp_path / "large.csv"
    async with CSVWriter().open(path) as writer:
        assert await writer.write_rows(rows()) == 5000
    async with CSVReader().rows(path, batch_size=256) as records:
        actual = [row async for row in records]
    assert len(actual) == 5000
    assert actual[-1] == ["4999", "value"]


async def test_csv_early_exit_closes_iterator(tmp_path):
    path = tmp_path / "early.csv"
    path.write_text("one\ntwo\n")
    async with CSVReader().rows(path) as records:
        assert await anext(records) == ["one"]
    with pytest.raises(StopAsyncIteration):
        await anext(records)


async def test_file_context_closes_when_cancelled(tmp_path):
    from anyio import CancelScope, sleep

    with CancelScope() as scope:
        async with FileWriter().open_text(tmp_path / "cancel.txt") as stream:
            await stream.write("written")
            scope.cancel()
            await sleep(0)
    assert stream.wrapped.closed


async def test_binary_stream_preserves_chunks_and_supports_empty_files(
    tmp_path,
):
    async def chunks():
        yield b"gold"
        yield b""
        yield b"bar"

    reader, writer = FileReader(), FileWriter()
    path = tmp_path / "stream.bin"
    assert await writer.write_stream(path, chunks()) == 7
    assert path.read_bytes() == b"goldbar"
    stream = reader.stream_bytes(path, 4)
    assert await anext(stream) == b"gold"
    assert await anext(stream) == b"bar"
    assert await anext(stream, None) is None
    with pytest.raises(FileExistsError):
        await writer.write_stream(path, chunks(), mode="xb")
    assert path.read_bytes() == b"goldbar"
    path.write_bytes(b"")
    assert await anext(reader.stream_bytes(path), None) is None


@pytest.mark.parametrize("size", [0, -1])
async def test_binary_stream_rejects_invalid_chunk_size(tmp_path, size):
    path = tmp_path / "stream.bin"
    path.write_bytes(b"gold")
    with pytest.raises(ValueError):
        await anext(FileReader().stream_bytes(path, size))


async def test_binary_stream_closes_handles_on_failure_and_early_exit(
    tmp_path, monkeypatch
):
    from contextlib import asynccontextmanager

    from anyio import open_file

    handles = []

    @asynccontextmanager
    async def tracked(path, **kwargs):
        async with await open_file(path, kwargs.get("mode", "rb")) as handle:
            handles.append(handle)
            yield handle

    reader, writer = FileReader(), FileWriter()
    monkeypatch.setattr(reader, "open_bytes", tracked)
    monkeypatch.setattr(writer, "open_bytes", tracked)

    async def broken():
        yield b"gold"
        raise OSError("source failed")

    path = tmp_path / "stream.bin"
    with pytest.raises(OSError, match="source failed"):
        await writer.write_stream(path, broken())
    assert handles[-1].wrapped.closed
    stream = reader.stream_bytes(path, 1)
    assert await anext(stream) == b"g"
    await stream.aclose()
    assert handles[-1].wrapped.closed


async def test_binary_chunks_leave_callers_stream_open(tmp_path):
    path = tmp_path / "stream.bin"
    path.write_bytes(b"gold")
    reader = FileReader()
    async with reader.open_bytes(path) as handle:
        chunks = reader.chunks(handle, 2)
        assert await anext(chunks) == b"go"
        await chunks.aclose()
        assert not handle.wrapped.closed
        assert await handle.read() == b"ld"
