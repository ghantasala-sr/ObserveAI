from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from shared.observeai.db import connect_with_retry, execute_db, init_schema
from shared.observeai.kafka import publish_event
from shared.observeai.logging import configure_logging
from shared.observeai.settings import CART_SERVICE_URL, HTTP_TIMEOUT_SECONDS, INVENTORY_SERVICE_URL, PAYMENT_SERVICE_URL
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "checkout-service"
app = FastAPI(title="ObserveAI Checkout Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)
db_pool = None

checkout_requests = meter.create_counter("checkout_requests_total")
checkout_successes = meter.create_counter("checkout_success_total")
checkout_failures = meter.create_counter("checkout_failure_total")
order_writes = meter.create_counter("order_writes_total")


class CheckoutItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class CheckoutRequest(BaseModel):
    user_id: str
    items: list[CheckoutItem] = Field(default_factory=list)
    amount: float = Field(gt=0)
    scenario: str | None = None
    idempotency_key: str | None = None


@app.on_event("startup")
async def startup():
    global db_pool
    db_pool = await connect_with_retry()
    await init_schema(db_pool)


@app.on_event("shutdown")
async def shutdown():
    if db_pool:
        await db_pool.close()


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/checkout")
async def checkout(request: CheckoutRequest):
    order_id = f"ord_{request.idempotency_key}" if request.idempotency_key else f"ord_{uuid4().hex[:12]}"
    attrs = {"scenario": request.scenario or "normal"}
    checkout_requests.add(1, attrs)

    with tracer.start_as_current_span("checkout.workflow") as span:
        span.set_attribute("order_id", order_id)
        span.set_attribute("user_id", request.user_id)
        span.set_attribute("scenario", request.scenario or "normal")
        span.set_attribute("checkout.amount", request.amount)

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                items = [item.model_dump() for item in request.items]
                if not items:
                    cart_response = await client.get(f"{CART_SERVICE_URL}/cart/{request.user_id}")
                    cart_response.raise_for_status()
                    items = cart_response.json().get("items", [])

                if not items:
                    checkout_failures.add(1, attrs)
                    span.set_status(Status(StatusCode.ERROR, "empty_cart"))
                    logger.warning(
                        "checkout failed because cart is empty",
                        extra={"order_id": order_id, "user_id": request.user_id, "scenario": request.scenario},
                    )
                    raise HTTPException(status_code=400, detail={"reason": "empty_cart"})

                inventory_response = await client.post(
                    f"{INVENTORY_SERVICE_URL}/inventory/reserve",
                    json={
                        "order_id": order_id,
                        "items": items,
                        "scenario": request.scenario,
                    },
                )
                inventory_response.raise_for_status()

                payment_response = await client.post(
                    f"{PAYMENT_SERVICE_URL}/payment/charge",
                    json={"order_id": order_id, "amount": request.amount, "scenario": request.scenario},
                )
                payment_response.raise_for_status()

            if db_pool:
                if request.scenario == "db_slow":
                    await execute_db(db_pool, tracer, "slow_query", "SELECT pg_sleep(1)")

                await execute_db(
                    db_pool,
                    tracer,
                    "insert_order",
                    """
                    INSERT INTO orders(order_id, user_id, amount, status, scenario)
                    VALUES($1, $2, $3, $4, $5)
                    ON CONFLICT(order_id) DO UPDATE
                    SET status = EXCLUDED.status,
                        amount = EXCLUDED.amount,
                        scenario = EXCLUDED.scenario,
                        updated_at = now()
                    """,
                    order_id,
                    request.user_id,
                    request.amount,
                    "completed",
                    request.scenario,
                )
                order_writes.add(1, attrs)

            await publish_event(
                "fraud.check.requested",
                {
                    "order_id": order_id,
                    "user_id": request.user_id,
                    "order_value": request.amount,
                    "item_count": sum(int(item.get("quantity", 0)) for item in items),
                    "scenario": request.scenario,
                },
                tracer,
                logger,
                order_id=order_id,
            )

            checkout_successes.add(1, attrs)
            logger.info("checkout completed", extra={"order_id": order_id, "user_id": request.user_id})
            return {"status": "completed", "order_id": order_id, "fraud_check": "queued"}

        except httpx.HTTPStatusError as exc:
            checkout_failures.add(1, attrs)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.warning(
                "checkout dependency rejected request",
                extra={"order_id": order_id, "scenario": request.scenario, "error_type": "dependency_http_error"},
            )
            raise HTTPException(status_code=exc.response.status_code, detail=exc.response.json()) from exc
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            checkout_failures.add(1, attrs)
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception(
                "checkout dependency unavailable",
                extra={"order_id": order_id, "scenario": request.scenario, "error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=503, detail={"reason": "dependency_unavailable"}) from exc
