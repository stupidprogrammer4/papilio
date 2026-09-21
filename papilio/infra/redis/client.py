from collections.abc import Awaitable, Callable
from typing import cast

from redis.asyncio import Redis


async def resolve[T](value: Awaitable[T] | T) -> T:
    """Await a redis-py return value only if it is awaitable.

    The async client types several commands as ``Awaitable[T] | T`` because the
    same method serves a pipeline, where the result is not a value yet. This
    keeps call sites free of that branch.
    """
    result: T
    if isinstance(value, Awaitable):
        result = await cast("Awaitable[T]", value)
    else:
        result = value
    return result


class RedisClient:
    """The async Redis client shared app-wide.

    `Redis` owns its connection pool internally, so one instance is the single
    client to inject everywhere. Use ``.client`` for any operation
    (``await rc.client.get(...)``); ``close()`` is wired to app shutdown.
    """

    def __init__(
        self,
        url: str,
        *,
        max_connections: int,
        socket_timeout: float,
        socket_connect_timeout: float,
        health_check_interval: int,
    ) -> None:
        self.client: Redis = Redis.from_url(
            url,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            health_check_interval=health_check_interval,
            decode_responses=True,
        )

    async def ping(self) -> bool:
        """
        Ask redis whether it is answering — for a health endpoint, or a test
        that would rather skip than fail against a store that is not there.

        Returns:
            (bool): Whether it answered.
        """
        pong = await resolve(self.client.ping())
        return bool(pong)

    async def count_keys(
        self, pattern: str, *, accept: Callable[[str], bool] | None = None
    ) -> int:
        """Count matching keys with incremental SCAN.

        The count is not a snapshot during concurrent key changes.
        """
        count = 0
        async for key in self.client.scan_iter(match=pattern, count=500):
            if accept is None or accept(key):
                count += 1
        return count

    async def close(self) -> None:
        await self.client.aclose()
