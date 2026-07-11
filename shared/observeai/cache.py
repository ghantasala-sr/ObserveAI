import json
from typing import Any

import redis.asyncio as redis
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.settings import REDIS_URL


def redis_client() -> redis.Redis:
    return redis.from_url(REDIS_URL, decode_responses=True)


async def redis_ping(client: redis.Redis, tracer) -> bool:
    with tracer.start_as_current_span("redis ping", kind=SpanKind.CLIENT, attributes={"db.system": "redis"}):
        return bool(await client.ping())


async def redis_set_json(client: redis.Redis, tracer, key: str, value: Any, ttl_seconds: int = 3600) -> None:
    with tracer.start_as_current_span(
        "redis set cart",
        kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "SET", "db.redis.key": key},
    ) as span:
        try:
            await client.set(key, json.dumps(value), ex=ttl_seconds)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


async def redis_get_json(client: redis.Redis, tracer, key: str) -> Any | None:
    with tracer.start_as_current_span(
        "redis get cart",
        kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "GET", "db.redis.key": key},
    ) as span:
        try:
            raw = await client.get(key)
            span.set_attribute("cache.hit", raw is not None)
            return json.loads(raw) if raw else None
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


async def redis_delete(client: redis.Redis, tracer, key: str) -> int:
    with tracer.start_as_current_span(
        "redis delete cart",
        kind=SpanKind.CLIENT,
        attributes={"db.system": "redis", "db.operation": "DEL", "db.redis.key": key},
    ) as span:
        try:
            return int(await client.delete(key))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
