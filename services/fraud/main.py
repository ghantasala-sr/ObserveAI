import asyncio

from fastapi import FastAPI
from opentelemetry.trace import SpanKind, Status, StatusCode

from shared.observeai.db import connect_with_retry, execute_db, init_schema
from shared.observeai.kafka import extract_context, make_consumer, publish_event
from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "ai-fraud-service"
app = FastAPI(title="ObserveAI AI Fraud Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)
db_pool = None

fraud_requests = meter.create_counter("fraud_requests_total")
high_risk_orders = meter.create_counter("fraud_high_risk_orders_total")
consumer_task: asyncio.Task | None = None


def score_order(order_value: float, item_count: int) -> tuple[float, str, str]:
    score = 0.15
    if order_value > 500:
        score += 0.4
    if item_count > 5:
        score += 0.25
    if order_value > 900 and item_count > 3:
        score += 0.15

    risk_score = min(score, 0.99)
    if risk_score >= 0.75:
        return risk_score, "review", "high_value_multi_item_order"
    if risk_score >= 0.45:
        return risk_score, "allow_with_monitoring", "moderate_order_risk"
    return risk_score, "allow", "low_order_risk"


async def consume_fraud_requests():
    consumer = make_consumer("fraud.check.requested", "observeai-fraud-v1")
    await consumer.start()
    try:
        async for message in consumer:
            payload = message.value
            order_id = payload.get("order_id")
            parent_context = extract_context(message.headers)

            with tracer.start_as_current_span(
                "fraud.inference",
                context=parent_context,
                kind=SpanKind.CONSUMER,
                attributes={
                    "messaging.system": "kafka",
                    "messaging.destination.name": "fraud.check.requested",
                    "messaging.operation": "process",
                    "order_id": order_id,
                },
            ) as span:
                try:
                    fraud_requests.add(1)
                    if payload.get("scenario") == "fraud_ai_slow":
                        await asyncio.sleep(1.5)

                    risk_score, decision, reason = score_order(
                        float(payload.get("order_value", 0)),
                        int(payload.get("item_count", 0)),
                    )
                    if decision == "review":
                        high_risk_orders.add(1)

                    result = {
                        "order_id": order_id,
                        "user_id": payload.get("user_id"),
                        "risk_score": round(risk_score, 3),
                        "decision": decision,
                        "reason": reason,
                        "model_version": "fraud-rules-v1",
                    }
                    span.set_attribute("fraud.risk_score", result["risk_score"])
                    span.set_attribute("fraud.decision", decision)
                    logger.info(
                        "fraud check completed",
                        extra={"order_id": order_id, "decision": decision, "risk_score": result["risk_score"]},
                    )
                    if db_pool:
                        await execute_db(
                            db_pool,
                            tracer,
                            "upsert_fraud_result",
                            """
                            INSERT INTO fraud_results(order_id, user_id, risk_score, decision, reason, model_version)
                            VALUES($1, $2, $3, $4, $5, $6)
                            ON CONFLICT(order_id) DO UPDATE
                            SET risk_score = EXCLUDED.risk_score,
                                decision = EXCLUDED.decision,
                                reason = EXCLUDED.reason,
                                model_version = EXCLUDED.model_version,
                                created_at = now()
                            """,
                            result["order_id"],
                            result["user_id"],
                            result["risk_score"],
                            result["decision"],
                            result["reason"],
                            result["model_version"],
                        )
                    await publish_event("fraud.check.completed", result, tracer, logger, order_id=order_id)
                    await consumer.commit()
                except Exception as exc:
                    span.record_exception(exc)
                    span.set_status(Status(StatusCode.ERROR, str(exc)))
                    logger.exception("fraud check failed", extra={"order_id": order_id, "error_type": type(exc).__name__})
                    await consumer.commit()
    finally:
        await consumer.stop()


@app.on_event("startup")
async def startup():
    global consumer_task
    global db_pool
    db_pool = await connect_with_retry()
    await init_schema(db_pool)
    consumer_task = asyncio.create_task(consume_fraud_requests())


@app.on_event("shutdown")
async def shutdown():
    if consumer_task:
        consumer_task.cancel()
    if db_pool:
        await db_pool.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}
