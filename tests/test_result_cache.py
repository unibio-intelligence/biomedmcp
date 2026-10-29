"""Shared result/page-cache failures must expose only the public error contract."""

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from biomedmcp.errors import ResearchError
from biomedmcp.runtime import ResultCache


@pytest.mark.parametrize("method", ["get", "put"])
async def test_shared_cache_loss_does_not_expose_redis_exception_credentials(method):
    class UnavailableRedis:
        async def get(self, *args):
            raise RedisConnectionError("redis://fixture:credential-sentinel@cache/15")

        async def set(self, *args, **kwargs):
            raise RedisConnectionError("redis://fixture:credential-sentinel@cache/15")

    cache = ResultCache(UnavailableRedis())
    with pytest.raises(ResearchError) as caught:
        if method == "get":
            await cache.get("page:fixture")
        else:
            await cache.put("page:fixture", {"records": []}, 60)
    assert caught.value.code == "cache_unavailable" and caught.value.retryable
    assert "credential-sentinel" not in str(caught.value.as_dict())
    assert caught.value.__suppress_context__


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b'{"credential-sentinel": NaN}',
        b"\xff",
        b'{"value":1e999}',
        b'{"value":-1e999}',
    ],
)
async def test_malformed_shared_cache_is_not_a_cache_miss_or_measurement(payload):
    class CorruptRedis:
        async def get(self, key):
            return payload

    with pytest.raises(ResearchError) as caught:
        await ResultCache(CorruptRedis()).get("page:fixture")
    assert caught.value.code == "cache_invalid_data" and not caught.value.retryable
    assert "credential-sentinel" not in str(caught.value)
