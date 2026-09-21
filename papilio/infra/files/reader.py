from collections.abc import AsyncGenerator, Awaitable
from contextlib import asynccontextmanager
from os import PathLike
from typing import Protocol

from anyio import AsyncFile, CancelScope, open_file


class ByteReader(Protocol):
    def read(self, size: int = -1) -> Awaitable[bytes]: ...


class FileReader:
    async def chunks(
        self, stream: ByteReader, chunk_size: int = 64 * 1024
    ) -> AsyncGenerator[bytes]:
        """Read bounded chunks without closing the caller's stream."""
        if chunk_size < 1:
            raise ValueError("chunk_size must be positive")
        while chunk := await stream.read(chunk_size):
            yield chunk

    async def stream_bytes(
        self, path: str | PathLike[str], chunk_size: int = 64 * 1024
    ) -> AsyncGenerator[bytes]:
        """Stream a file and close it when iteration ends."""
        async with self.open_bytes(path) as stream:
            async for chunk in self.chunks(stream, chunk_size):
                yield chunk

    @asynccontextmanager
    async def open_text(
        self,
        path: str | PathLike[str],
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
        newline: str | None = None,
    ) -> AsyncGenerator[AsyncFile[str]]:
        stream = await open_file(
            path, "r", encoding=encoding, errors=errors, newline=newline
        )
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    @asynccontextmanager
    async def open_bytes(
        self, path: str | PathLike[str]
    ) -> AsyncGenerator[AsyncFile[bytes]]:
        stream = await open_file(path, "rb")
        try:
            yield stream
        finally:
            with CancelScope(shield=True):
                await stream.aclose()

    async def read_text(
        self,
        path: str | PathLike[str],
        *,
        encoding: str = "utf-8",
        errors: str = "strict",
    ) -> str:
        async with self.open_text(path, encoding=encoding, errors=errors) as f:
            return await f.read()

    async def read_bytes(self, path: str | PathLike[str]) -> bytes:
        async with self.open_bytes(path) as stream:
            return await stream.read()
