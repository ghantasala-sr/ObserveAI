import asyncio
import itertools
import random

import httpx
from opentelemetry.trace import Status, StatusCode

from shared.observeai.logging import configure_logging
from shared.observeai.settings import CART_SERVICE_URL, HTTP_TIMEOUT_SECONDS, TRAFFIC_BURST_SIZE, TRAFFIC_INTERVAL_SECONDS
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "traffic-generator"
tracer, meter = setup_telemetry(SERVICE_NAME)
logger = configure_logging(SERVICE_NAME)

traffic_requests = meter.create_counter("traffic_generator_requests_total")
traffic_failures = meter.create_counter("traffic_generator_failures_total")
traffic_loops = meter.create_counter("traffic_generator_loops_total")

CHECKOUT_SERVICE_URL = "http://checkout-service:8000"

SCENARIOS = [
    {"scenario": "normal", "amount": 99.0, "quantity": 1, "expected": 200},
    {"scenario": "payment_slow", "amount": 349.0, "quantity": 2, "expected": 200},
    {"scenario": "fraud_ai_slow", "amount": 1200.0, "quantity": 6, "expected": 200},
    {"scenario": "kafka_consumer_slow", "amount": 999.0, "quantity": 4, "expected": 200},
    {"scenario": "poison_message", "amount": 459.0, "quantity": 2, "expected": 200},
    {"scenario": "notification_slow", "amount": 219.0, "quantity": 1, "expected": 200},
    {"scenario": "notification_fail", "amount": 189.0, "quantity": 1, "expected": 200},
    {"scenario": "analytics_slow", "amount": 879.0, "quantity": 3, "expected": 200},
    {"scenario": "db_slow", "amount": 799.0, "quantity": 1, "expected": 200},
    {"scenario": "payment_fail", "amount": 249.0, "quantity": 1, "expected": 502},
    {"scenario": "provider_timeout", "amount": 629.0, "quantity": 2, "expected": 502},
    {"scenario": "inventory_fail", "amount": 179.0, "quantity": 1, "expected": 409},
]


async def wait_for_services(client: httpx.AsyncClient) -> None:
    for _ in range(60):
        try:
            checkout = await client.get(f"{CHECKOUT_SERVICE_URL}/health")
            cart = await client.get(f"{CART_SERVICE_URL}/health")
            if checkout.status_code == 200 and cart.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(1)
    raise RuntimeError("ObserveAI services did not become ready")


async def seed_cart(client: httpx.AsyncClient, user_id: str, index: int) -> None:
    with tracer.start_as_current_span("traffic seed cart") as span:
        span.set_attribute("user_id", user_id)
        response = await client.post(
            f"{CART_SERVICE_URL}/cart",
            json={
                "user_id": user_id,
                "items": [
                    {"product_id": f"cart_item_{index % 5}", "quantity": 1},
                    {"product_id": f"addon_{index % 3}", "quantity": 2},
                ],
            },
        )
        response.raise_for_status()


async def call_checkout(client: httpx.AsyncClient, index: int, scenario_config: dict, use_cart: bool) -> None:
    scenario = scenario_config["scenario"]
    user_id = f"traffic_user_{index % 20}"
    idempotency_key = f"traffic-{index}-{scenario}-{random.randint(1000, 9999)}"
    expected = scenario_config["expected"]

    payload = {
        "user_id": user_id,
        "amount": scenario_config["amount"],
        "scenario": scenario,
        "idempotency_key": idempotency_key,
    }

    if use_cart:
        await seed_cart(client, user_id, index)
    else:
        payload["items"] = [{"product_id": f"item_{index % 7}", "quantity": scenario_config["quantity"]}]

    with tracer.start_as_current_span("traffic checkout request") as span:
        span.set_attribute("scenario", scenario)
        span.set_attribute("expected_status", expected)
        span.set_attribute("uses_cart", use_cart)
        try:
            response = await client.post(f"{CHECKOUT_SERVICE_URL}/checkout", json=payload)
            traffic_requests.add(1, {"scenario": scenario, "status_code": str(response.status_code)})
            span.set_attribute("http.status_code", response.status_code)

            if response.status_code != expected:
                traffic_failures.add(1, {"scenario": scenario, "reason": "unexpected_status"})
                span.set_status(Status(StatusCode.ERROR, f"expected {expected}, got {response.status_code}"))
                logger.warning(
                    "traffic request returned unexpected status",
                    extra={"scenario": scenario, "error_type": "unexpected_status"},
                )
            else:
                logger.info("traffic request completed", extra={"scenario": scenario})
        except Exception as exc:
            traffic_failures.add(1, {"scenario": scenario, "reason": type(exc).__name__})
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception("traffic request failed", extra={"scenario": scenario, "error_type": type(exc).__name__})


async def main() -> None:
    timeout = httpx.Timeout(HTTP_TIMEOUT_SECONDS + 3.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await wait_for_services(client)
        logger.info("traffic generator started")

        scenario_cycle = itertools.cycle(SCENARIOS)
        index = 0
        while True:
            traffic_loops.add(1)
            tasks = []
            for _ in range(TRAFFIC_BURST_SIZE):
                index += 1
                scenario_config = next(scenario_cycle)
                use_cart = index % 5 == 0 and scenario_config["expected"] == 200
                tasks.append(call_checkout(client, index, scenario_config, use_cart))
            await asyncio.gather(*tasks)
            await asyncio.sleep(TRAFFIC_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
