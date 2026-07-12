import asyncio
from uuid import uuid4

from aiokafka import TopicPartition
from fastapi import FastAPI
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.db import connect_with_retry, execute_db, init_schema
from shared.observeai.kafka import extract_context, make_consumer
from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "analytics-service"
app = FastAPI(title="ObserveAI Analytics Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)
db_pool = None
completed_consumer_task: asyncio.Task | None = None
dlq_consumer_task: asyncio.Task | None = None

analytics_events = meter.create_counter("analytics_events_total")
analytics_failures = meter.create_counter("analytics_failures_total")
high_risk_analytics_events = meter.create_counter("analytics_high_risk_orders_total")
dlq_analytics_events = meter.create_counter("analytics_dlq_events_total")


def estimate_lag(consumer, message) -> int:
    topic_partition = TopicPartition(message.topic, message.partition)
    highwater = consumer.highwater(topic_partition)
    if highwater is None:
        return 0
    return max(int(highwater) - int(message.offset) - 1, 0)


async def write_analytics_event(payload: dict, event_type: str, status: str, tracer) -> None:
    if not db_pool:
        return
    await execute_db(
        db_pool,
        tracer,
        "insert_analytics_event",
        """
        INSERT INTO analytics_events(event_id, event_type, order_id, user_id, scenario, decision, risk_score, status)
        VALUES($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT(event_id) DO NOTHING
        """,
        f"evt_{uuid4().hex[:12]}",
        event_type,
        payload.get("order_id"),
        payload.get("user_id"),
        payload.get("scenario"),
        payload.get("decision"),
        payload.get("risk_score"),
        status,
    )


async def consume_fraud_completed():
    consumer = make_consumer("fraud.check.completed", "observeai-analytics-completed-v2", auto_offset_reset="latest")
    await consumer.start()
    try:
        async for message in consumer:
            payload = message.value
            order_id = payload.get("order_id")
            scenario = payload.get("scenario") or "normal"
            parent_context = extract_context(message.headers)

            with tracer.start_as_current_span(
                "analytics.process_fraud_completed",
                context=parent_context,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": "fraud.check.completed",
                    "messaging.operation": "process",
                    "order_id": order_id,
                    "scenario": scenario,
                },
            ) as span:
                try:
                    lag = estimate_lag(consumer, message)
                    span.set_attribute("kafka.consumer.lag_estimate", lag)
                    if scenario == "analytics_slow":
                        await asyncio.sleep(1.5)

                    analytics_events.add(1, {"event_type": "fraud_completed", "scenario": scenario})
                    if payload.get("decision") == "review":
                        high_risk_analytics_events.add(1, {"scenario": scenario})
                    await write_analytics_event(payload, "fraud_completed", "processed", tracer)
                    logger.info("analytics event processed", extra={"order_id": order_id, "scenario": scenario})
                    await consumer.commit()
                except Exception as exc:
                    analytics_failures.add(1, {"event_type": "fraud_completed", "error_type": type(exc).__name__})
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    logger.exception(
                        "analytics processing failed",
                        extra={"order_id": order_id, "scenario": scenario, "error_type": type(exc).__name__},
                    )
                    await consumer.commit()
    finally:
        await consumer.stop()


async def consume_fraud_dlq():
    consumer = make_consumer("fraud.check.dlq", "observeai-analytics-dlq-v2", auto_offset_reset="latest")
    await consumer.start()
    try:
        async for message in consumer:
            payload = message.value
            order_id = payload.get("order_id")
            scenario = payload.get("scenario") or "unknown"
            parent_context = extract_context(message.headers)

            with tracer.start_as_current_span(
                "analytics.process_fraud_dlq",
                context=parent_context,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": "fraud.check.dlq",
                    "messaging.operation": "process",
                    "order_id": order_id,
                    "scenario": scenario,
                },
            ) as span:
                try:
                    lag = estimate_lag(consumer, message)
                    span.set_attribute("kafka.consumer.lag_estimate", lag)
                    dlq_analytics_events.add(1, {"scenario": scenario})
                    await write_analytics_event(payload, "fraud_dlq", "processed", tracer)
                    logger.warning("analytics dlq event processed", extra={"order_id": order_id, "scenario": scenario})
                    await consumer.commit()
                except Exception as exc:
                    analytics_failures.add(1, {"event_type": "fraud_dlq", "error_type": type(exc).__name__})
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    logger.exception(
                        "analytics dlq processing failed",
                        extra={"order_id": order_id, "scenario": scenario, "error_type": type(exc).__name__},
                    )
                    await consumer.commit()
    finally:
        await consumer.stop()


@app.on_event("startup")
async def startup():
    global completed_consumer_task
    global dlq_consumer_task
    global db_pool
    db_pool = await connect_with_retry()
    await init_schema(db_pool)
    completed_consumer_task = asyncio.create_task(consume_fraud_completed())
    dlq_consumer_task = asyncio.create_task(consume_fraud_dlq())


@app.on_event("shutdown")
async def shutdown():
    if completed_consumer_task:
        completed_consumer_task.cancel()
    if dlq_consumer_task:
        dlq_consumer_task.cancel()
    if db_pool:
        await db_pool.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}
