from fastapi import FastAPI
from pydantic import BaseModel, Field

from shared.observeai.cache import redis_client, redis_delete, redis_get_json, redis_ping, redis_set_json
from shared.observeai.logging import configure_logging
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "cart-service"
app = FastAPI(title="ObserveAI Cart Service")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)
redis = redis_client()

cart_requests = meter.create_counter("cart_requests_total")
cart_cache_hits = meter.create_counter("cart_cache_hits_total")
cart_cache_misses = meter.create_counter("cart_cache_misses_total")


class CartItem(BaseModel):
    product_id: str
    quantity: int = Field(gt=0)


class CartRequest(BaseModel):
    user_id: str
    items: list[CartItem]


@app.get("/health")
async def health():
    await redis_ping(redis, tracer)
    return {"status": "ok", "service": SERVICE_NAME}


@app.post("/cart")
async def set_cart(request: CartRequest):
    cart_requests.add(1, {"operation": "set"})
    key = f"cart:{request.user_id}"
    items = [item.model_dump() for item in request.items]
    await redis_set_json(redis, tracer, key, {"user_id": request.user_id, "items": items})
    logger.info("cart stored", extra={"user_id": request.user_id})
    return {"status": "stored", "user_id": request.user_id, "items": items}


@app.get("/cart/{user_id}")
async def get_cart(user_id: str):
    cart_requests.add(1, {"operation": "get"})
    key = f"cart:{user_id}"
    cart = await redis_get_json(redis, tracer, key)
    if cart:
        cart_cache_hits.add(1)
        logger.info("cart cache hit", extra={"user_id": user_id})
        return cart

    cart_cache_misses.add(1)
    logger.info("cart cache miss", extra={"user_id": user_id})
    return {"user_id": user_id, "items": []}


@app.delete("/cart/{user_id}")
async def clear_cart(user_id: str):
    cart_requests.add(1, {"operation": "delete"})
    deleted = await redis_delete(redis, tracer, f"cart:{user_id}")
    logger.info("cart cleared", extra={"user_id": user_id})
    return {"status": "cleared", "deleted": deleted}
