import asyncio
from collections.abc import Sequence
from typing import Any

import asyncpg
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.settings import POSTGRES_DSN


async def connect_with_retry(attempts: int = 30) -> asyncpg.Pool:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            return await asyncpg.create_pool(POSTGRES_DSN, min_size=1, max_size=5)
        except Exception as exc:
            last_error = exc
            await asyncio.sleep(1)
    raise RuntimeError("postgres connection failed") from last_error


async def init_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
              order_id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              amount NUMERIC NOT NULL,
              status TEXT NOT NULL,
              scenario TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS fraud_results (
              order_id TEXT PRIMARY KEY,
              user_id TEXT,
              risk_score NUMERIC NOT NULL,
              decision TEXT NOT NULL,
              reason TEXT NOT NULL,
              model_version TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS notifications (
              notification_id TEXT PRIMARY KEY,
              order_id TEXT NOT NULL,
              user_id TEXT,
              channel TEXT NOT NULL,
              status TEXT NOT NULL,
              reason TEXT,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS analytics_events (
              event_id TEXT PRIMARY KEY,
              event_type TEXT NOT NULL,
              order_id TEXT,
              user_id TEXT,
              scenario TEXT,
              decision TEXT,
              risk_score NUMERIC,
              status TEXT NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """
        )


async def execute_db(pool: asyncpg.Pool, tracer, operation: str, query: str, *args: Sequence[Any]):
    with tracer.start_as_current_span(
        f"postgres {operation}",
        kind=SpanKind.CLIENT,
        attributes={
            "db.system": "postgresql",
            "db.operation": operation,
        },
    ) as span:
        try:
            async with pool.acquire() as conn:
                return await conn.execute(query, *args)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
