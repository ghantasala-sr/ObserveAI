import asyncio
import json
from collections.abc import Mapping
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from opentelemetry import context, propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.settings import KAFKA_MAX_RETRIES, REDPANDA_BROKERS


class HeaderCarrier(dict):
    def set(self, key: str, value: str) -> None:
        self[key] = value


def inject_headers() -> list[tuple[str, bytes]]:
    carrier: HeaderCarrier = HeaderCarrier()
    propagate.inject(carrier)
    return [(key, value.encode("utf-8")) for key, value in carrier.items()]


def extract_context(headers: list[tuple[str, bytes]] | None):
    carrier = {}
    for key, value in headers or []:
        try:
            carrier[key] = value.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return propagate.extract(carrier)


async def publish_event(
    topic: str,
    value: Mapping[str, Any],
    tracer,
    logger,
    *,
    order_id: str | None = None,
) -> None:
    producer = AIOKafkaProducer(
        bootstrap_servers=REDPANDA_BROKERS,
        value_serializer=lambda payload: json.dumps(payload).encode("utf-8"),
    )
    await producer.start()
    try:
        with tracer.start_as_current_span(
            f"kafka publish {topic}",
            kind=SpanKind.PRODUCER,
            attributes={
                "messaging.system": "kafka",
                "messaging.destination.name": topic,
                "messaging.operation": "publish",
            },
        ) as span:
            if order_id:
                span.set_attribute("order_id", order_id)

            for attempt in range(KAFKA_MAX_RETRIES + 1):
                try:
                    await producer.send_and_wait(topic, dict(value), headers=inject_headers())
                    logger.info("kafka event published", extra={"topic": topic, "order_id": order_id})
                    return
                except Exception as exc:
                    span.record_exception(exc)
                    if attempt >= KAFKA_MAX_RETRIES:
                        span.set_status(Status(StatusCode.ERROR, str(exc)))
                        logger.exception("kafka publish failed", extra={"topic": topic, "order_id": order_id})
                        raise
                    await asyncio.sleep(0.2 * (2**attempt))
    finally:
        await producer.stop()


def make_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=REDPANDA_BROKERS,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        value_deserializer=lambda payload: json.loads(payload.decode("utf-8")),
    )
