import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from redis.exceptions import ConnectionError

from papilio.infra.redis.client import RedisClient, resolve


@pytest.fixture
async def redis_client() -> AsyncIterator[RedisClient]:
    url = os.environ.get("PAPILIO_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set PAPILIO_TEST_REDIS_URL for Redis integration tests")
    client = RedisClient(
        url,
        max_connections=4,
        socket_timeout=2,
        socket_connect_timeout=2,
        health_check_interval=30,
    )
    try:
        await client.ping()
        yield client
    finally:
        await client.close()


async def test_count_keys_scans_multiple_batches_and_filters(
    redis_client: RedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefix = f"test:count:{uuid4().hex}:"
    keys = {f"{prefix}{index}": "value" for index in range(1203)}
    keys[prefix + "one__progress"] = "progress"
    keys[prefix + "two__progress"] = "progress"
    calls = 0
    scan = redis_client.client.scan

    async def tracked(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await scan(*args, **kwargs)

    def blocked(*args, **kwargs):
        raise AssertionError("KEYS is not incremental")

    monkeypatch.setattr(redis_client.client, "scan", tracked)
    monkeypatch.setattr(redis_client.client, "keys", blocked)
    try:
        assert await redis_client.count_keys(prefix + "*") == 0
        await resolve(redis_client.client.mset(keys))
        assert await redis_client.count_keys(prefix + "*") == 1205
        assert (
            await redis_client.count_keys(
                prefix + "*", accept=lambda key: "progress" not in key
            )
            == 1203
        )
        assert await redis_client.count_keys(prefix + "missing:*") == 0
        assert calls > 4
        assert await resolve(redis_client.client.exists(*keys)) == 1205
    finally:
        await resolve(redis_client.client.delete(*keys))


async def test_count_keys_propagates_scan_failure(
    redis_client: RedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failed(**kwargs) -> AsyncIterator[str]:
        yield "partial"
        raise ConnectionError("disconnected")

    monkeypatch.setattr(redis_client.client, "scan_iter", failed)
    with pytest.raises(ConnectionError, match="disconnected"):
        await redis_client.count_keys("test:*")


async def test_count_keys_propagates_filter_failure(
    redis_client: RedisClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def keys(**kwargs) -> AsyncIterator[str]:
        yield "one"

    def broken(key: str) -> bool:
        raise ValueError("invalid filter")

    monkeypatch.setattr(redis_client.client, "scan_iter", keys)
    with pytest.raises(ValueError, match="invalid filter"):
        await redis_client.count_keys("*", accept=broken)
