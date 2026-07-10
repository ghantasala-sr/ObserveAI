from fastapi import FastAPI, HTTPException
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "inventory-service"
app = FastAPI(title="ObserveAI Inventory Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)

inventory_reservations = meter.create_counter("inventory_reservations_total")
out_of_stock = meter.create_counter("inventory_out_of_stock_total")


class InventoryItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class InventoryRequest(BaseModel):
    order_id: str
    items: list[InventoryItem]
    scenario: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/inventory/reserve")
async def reserve_inventory(request: InventoryRequest):
    attrs = {"scenario": request.scenario or "normal"}
    inventory_reservations.add(1, attrs)

    with tracer.start_as_current_span("inventory.reserve") as span:
        span.set_attribute("order_id", request.order_id)
        span.set_attribute("inventory.item_count", len(request.items))
        span.set_attribute("scenario", request.scenario or "normal")

        if request.scenario == "inventory_fail":
            out_of_stock.add(1, attrs)
            span.set_status(Status(StatusCode.ERROR, "out_of_stock"))
            logger.warning(
                "inventory reservation failed",
                extra={"order_id": request.order_id, "scenario": request.scenario, "error_type": "out_of_stock"},
            )
            raise HTTPException(status_code=409, detail={"reason": "out_of_stock"})

        logger.info("inventory reserved", extra={"order_id": request.order_id, "scenario": request.scenario})
        return {"status": "reserved", "order_id": request.order_id}
