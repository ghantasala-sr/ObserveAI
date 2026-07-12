import asyncio
from uuid import uuid4

from aiokafka import TopicPartition
from fastapi import FastAPI
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.db import connect_with_retry, execute_db, init_schema
from shared.observeai.kafka import extract_context, make_consumer
from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "notification-service"
app = FastAPI(title="ObserveAI Notification Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)
db_pool = None
consumer_task: asyncio.Task | None = None

notifications_sent = meter.create_counter("notifications_sent_total")
notifications_failed = meter.create_counter("notifications_failed_total")
notifications_processed = meter.create_counter("notifications_processed_total")


def estimate_lag(consumer, message) -> int:
    topic_partition = TopicPartition(message.topic, message.partition)
    highwater = consumer.highwater(topic_partition)
    if highwater is None:
        return 0
    return max(int(highwater) - int(message.offset) - 1, 0)


async def consume_fraud_completed():
    consumer = make_consumer("fraud.check.completed", "observeai-notification-v2", auto_offset_reset="latest")
    await consumer.start()
    try:
        async for message in consumer:
            payload = message.value
            order_id = payload.get("order_id")
            scenario = payload.get("scenario") or "normal"
            parent_context = extract_context(message.headers)

            with tracer.start_as_current_span(
                "notification.send",
                context=parent_context,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": "fraud.check.completed",
                    "messaging.operation": "process",
                    "notification.channel": "email",
                    "order_id": order_id,
                    "scenario": scenario,
                },
            ) as span:
                try:
                    lag = estimate_lag(consumer, message)
                    span.set_attribute("kafka.consumer.lag_estimate", lag)
                    notifications_processed.add(1, {"scenario": scenario})

                    if scenario == "notification_slow":
                        await asyncio.sleep(2.0)

                    if scenario == "notification_fail":
                        raise RuntimeError("simulated notification provider failure")

                    notifications_sent.add(1, {"scenario": scenario, "channel": "email"})
                    if db_pool:
                        await execute_db(
                            db_pool,
                            tracer,
                            "insert_notification",
                            """
                            INSERT INTO notifications(notification_id, order_id, user_id, channel, status, reason)
                            VALUES($1, $2, $3, $4, $5, $6)
                            ON CONFLICT(notification_id) DO NOTHING
                            """,
                            f"ntf_{uuid4().hex[:12]}",
                            order_id,
                            payload.get("user_id"),
                            "email",
                            "sent",
                            payload.get("decision"),
                        )
                    logger.info("notification sent", extra={"order_id": order_id, "scenario": scenario})
                    await consumer.commit()
                except Exception as exc:
                    notifications_failed.add(1, {"scenario": scenario, "error_type": type(exc).__name__})
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    if db_pool:
                        await execute_db(
                            db_pool,
                            tracer,
                            "insert_notification_failure",
                            """
                            INSERT INTO notifications(notification_id, order_id, user_id, channel, status, reason)
                            VALUES($1, $2, $3, $4, $5, $6)
                            ON CONFLICT(notification_id) DO NOTHING
                            """,
                            f"ntf_{uuid4().hex[:12]}",
                            order_id,
                            payload.get("user_id"),
                            "email",
                            "failed",
                            type(exc).__name__,
                        )
                    logger.exception(
                        "notification failed",
                        extra={"order_id": order_id, "scenario": scenario, "error_type": type(exc).__name__},
                    )
                    await consumer.commit()
    finally:
        await consumer.stop()


@app.on_event("startup")
async def startup():
    global consumer_task
    global db_pool
    db_pool = await connect_with_retry()
    await init_schema(db_pool)
    consumer_task = asyncio.create_task(consume_fraud_completed())


@app.on_event("shutdown")
async def shutdown():
    if consumer_task:
        consumer_task.cancel()
    if db_pool:
        await db_pool.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}
