import asyncio

from fastapi import FastAPI, HTTPException
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "payment-service"
app = FastAPI(title="ObserveAI Payment Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)

payment_requests = meter.create_counter("payment_requests_total")
payment_failures = meter.create_counter("payment_failures_total")


class PaymentRequest(BaseModel):
    order_id: str
    amount: float = Field(gt=0)
    scenario: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/payment/charge")
async def charge_payment(request: PaymentRequest):
    attrs = {"scenario": request.scenario or "normal"}
    payment_requests.add(1, attrs)

    with tracer.start_as_current_span("payment.provider_call") as span:
        span.set_attribute("order_id", request.order_id)
        span.set_attribute("payment.amount", request.amount)
        span.set_attribute("scenario", request.scenario or "normal")

        if request.scenario == "payment_slow":
            await asyncio.sleep(1.2)

        if request.scenario in {"payment_fail", "provider_timeout"}:
            payment_failures.add(1, attrs)
            reason = "provider_timeout" if request.scenario == "provider_timeout" else "payment_declined"
            span.set_status(Status(StatusCode.ERROR, reason))
            logger.error(
                "payment failed",
                extra={"order_id": request.order_id, "scenario": request.scenario, "error_type": reason},
            )
            raise HTTPException(status_code=502, detail={"reason": reason})

        logger.info("payment completed", extra={"order_id": request.order_id, "scenario": request.scenario})
        return {
            "status": "completed",
            "order_id": request.order_id,
            "provider_reference": f"pay_{request.order_id[-8:]}",
        }
