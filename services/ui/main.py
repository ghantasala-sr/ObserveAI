from datetime import datetime, timezone
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from shared.observeai.logging import configure_logging
from shared.observeai.settings import CART_SERVICE_URL, HTTP_TIMEOUT_SECONDS
from shared.observeai.telemetry import setup_telemetry


SERVICE_NAME = "ui-service"
CHECKOUT_SERVICE_URL = "http://checkout-service:8000"
INTERNAL_SERVICES = {
    "checkout-service": "http://checkout-service:8000/health",
    "cart-service": "http://cart-service:8000/health",
    "payment-service": "http://payment-service:8000/health",
    "inventory-service": "http://inventory-service:8000/health",
    "ai-fraud-service": "http://ai-fraud-service:8000/health",
    "notification-service": "http://notification-service:8000/health",
    "analytics-service": "http://analytics-service:8000/health",
}

SCENARIOS = {
    "normal": {"amount": 99.0, "quantity": 1, "expected": "Checkout succeeds and async fraud is queued."},
    "payment_slow": {"amount": 349.0, "quantity": 2, "expected": "Payment span becomes slow; checkout p99 rises."},
    "payment_fail": {"amount": 249.0, "quantity": 1, "expected": "Payment returns an expected 502 failure."},
    "provider_timeout": {"amount": 629.0, "quantity": 2, "expected": "Payment provider timeout-style failure."},
    "inventory_fail": {"amount": 179.0, "quantity": 1, "expected": "Inventory returns out-of-stock."},
    "fraud_ai_slow": {"amount": 1200.0, "quantity": 6, "expected": "Fraud inference latency spikes."},
    "kafka_consumer_slow": {"amount": 999.0, "quantity": 4, "expected": "Fraud Kafka consumer lag increases."},
    "poison_message": {"amount": 459.0, "quantity": 2, "expected": "Fraud retries and publishes to DLQ."},
    "notification_slow": {"amount": 219.0, "quantity": 1, "expected": "Notification consumer latency spikes."},
    "notification_fail": {"amount": 189.0, "quantity": 1, "expected": "Notification provider failure is recorded."},
    "analytics_slow": {"amount": 879.0, "quantity": 3, "expected": "Analytics consumer latency spikes."},
    "db_slow": {"amount": 799.0, "quantity": 1, "expected": "Postgres slow query appears in traces."},
}

app = FastAPI(title="ObserveAI UI")
tracer, meter = setup_telemetry(SERVICE_NAME, app)
logger = configure_logging(SERVICE_NAME)

ui_scenario_triggers = meter.create_counter("ui_scenario_triggers_total")
ui_scenario_failures = meter.create_counter("ui_scenario_failures_total")


class ScenarioRequest(BaseModel):
    scenario: str
    use_cart: bool = False


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(content=HTML)


@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/api/services")
async def services():
    statuses = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(1.5)) as client:
        for name, url in INTERNAL_SERVICES.items():
            started = datetime.now(timezone.utc)
            try:
                response = await client.get(url)
                latency_ms = round((datetime.now(timezone.utc) - started).total_seconds() * 1000, 2)
                statuses.append(
                    {
                        "name": name,
                        "status": "ok" if response.status_code == 200 else "degraded",
                        "latency_ms": latency_ms,
                    }
                )
            except Exception as exc:
                statuses.append({"name": name, "status": "down", "latency_ms": None, "error": type(exc).__name__})
    return {"services": statuses}


@app.post("/api/cart/seed")
async def seed_cart():
    user_id = f"ui_cart_user_{uuid4().hex[:6]}"
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{CART_SERVICE_URL}/cart",
            json={
                "user_id": user_id,
                "items": [
                    {"product_id": "keyboard", "quantity": 1},
                    {"product_id": "mouse", "quantity": 1},
                    {"product_id": "usb_hub", "quantity": 2},
                ],
            },
        )
        response.raise_for_status()
    logger.info("ui seeded cart", extra={"user_id": user_id})
    return {"status": "stored", "user_id": user_id}


@app.post("/api/scenarios")
async def trigger_scenario(request: ScenarioRequest):
    if request.scenario not in SCENARIOS:
        raise HTTPException(status_code=400, detail={"reason": "unknown_scenario", "scenario": request.scenario})

    scenario = SCENARIOS[request.scenario]
    user_id = f"ui_user_{uuid4().hex[:6]}"
    idempotency_key = f"ui-{request.scenario}-{uuid4().hex[:8]}"
    payload = {
        "user_id": user_id,
        "amount": scenario["amount"],
        "scenario": request.scenario,
        "idempotency_key": idempotency_key,
    }
    if request.use_cart:
        await seed_cart_for_user(user_id)
    else:
        payload["items"] = [{"product_id": f"ui_{request.scenario}", "quantity": scenario["quantity"]}]

    with tracer.start_as_current_span("ui.trigger_scenario") as span:
        span.set_attribute("scenario", request.scenario)
        span.set_attribute("uses_cart", request.use_cart)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS + 4.0)) as client:
                response = await client.post(f"{CHECKOUT_SERVICE_URL}/checkout", json=payload)
            ui_scenario_triggers.add(1, {"scenario": request.scenario, "status_code": str(response.status_code)})
            logger.info(
                "ui scenario triggered",
                extra={"scenario": request.scenario, "status_code": response.status_code},
            )
            return {
                "scenario": request.scenario,
                "status_code": response.status_code,
                "expected": scenario["expected"],
                "response": safe_json(response),
            }
        except Exception as exc:
            ui_scenario_failures.add(1, {"scenario": request.scenario, "error_type": type(exc).__name__})
            logger.exception("ui scenario failed", extra={"scenario": request.scenario, "error_type": type(exc).__name__})
            raise HTTPException(status_code=502, detail={"reason": "scenario_trigger_failed"}) from exc


async def seed_cart_for_user(user_id: str) -> None:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"{CART_SERVICE_URL}/cart",
            json={
                "user_id": user_id,
                "items": [
                    {"product_id": "cart_keyboard", "quantity": 1},
                    {"product_id": "cart_addon", "quantity": 2},
                ],
            },
        )
        response.raise_for_status()


def safe_json(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return {"body": response.text}


HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>ObserveAI Control Room</title>
  <style>
    :root {
      --bg: #08090b;
      --panel: #111318;
      --panel-2: #171a21;
      --text: #f6f1e8;
      --muted: #969ca8;
      --line: rgba(255,255,255,.12);
      --accent: #ff5b35;
      --accent-2: #ffb199;
      --ok: #65d6a6;
      --warn: #ffd166;
      --bad: #ff6b6b;
      --shadow: 0 24px 80px rgba(0,0,0,.45);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 75% 8%, rgba(255,91,53,.20), transparent 34rem),
        radial-gradient(circle at 8% 24%, rgba(255,177,153,.09), transparent 28rem),
        linear-gradient(180deg, #090a0d 0%, #050608 100%);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.035) 1px, transparent 1px);
      background-size: 48px 48px;
      mask-image: linear-gradient(to bottom, rgba(0,0,0,.8), transparent 72%);
    }
    header {
      padding: 32px clamp(20px, 4vw, 64px) 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 24px;
      animation: rise .55s ease both;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }
    .mark {
      width: 42px;
      height: 42px;
      border-radius: 14px;
      display: grid;
      place-items: center;
      color: #160703;
      background: linear-gradient(135deg, var(--accent), var(--accent-2));
      box-shadow: 0 12px 40px rgba(255,91,53,.32);
      font-weight: 900;
      letter-spacing: -.08em;
    }
    .brand h1 {
      margin: 0;
      font-size: clamp(24px, 3vw, 40px);
      letter-spacing: -.06em;
      line-height: 1;
    }
    .brand p, .top-actions p {
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .top-actions {
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    a, button {
      color: inherit;
      font: inherit;
    }
    .button {
      border: 1px solid var(--line);
      background: rgba(255,255,255,.055);
      color: var(--text);
      text-decoration: none;
      padding: 10px 14px;
      border-radius: 999px;
      cursor: pointer;
      transition: transform .18s ease, border-color .18s ease, background .18s ease;
    }
    .button.primary {
      border-color: rgba(255,91,53,.55);
      background: linear-gradient(135deg, rgba(255,91,53,.92), rgba(255,120,74,.78));
      box-shadow: 0 16px 38px rgba(255,91,53,.22);
    }
    .button:hover {
      transform: translateY(-2px);
      border-color: rgba(255,255,255,.34);
    }
    main {
      padding: 12px clamp(20px, 4vw, 64px) 48px;
      display: grid;
      grid-template-columns: minmax(320px, .88fr) minmax(420px, 1.35fr);
      gap: clamp(20px, 3vw, 42px);
    }
    .intro {
      position: sticky;
      top: 20px;
      align-self: start;
      animation: rise .7s ease .05s both;
      min-width: 0;
    }
    .eyebrow {
      color: var(--accent-2);
      text-transform: uppercase;
      letter-spacing: .16em;
      font-size: 12px;
      font-weight: 700;
    }
    .intro h2 {
      margin: 14px 0 18px;
      font-size: clamp(48px, 8vw, 92px);
      line-height: .82;
      letter-spacing: -.085em;
      max-width: 680px;
    }
    .intro .copy {
      color: #c8cbd2;
      max-width: 560px;
      line-height: 1.65;
      font-size: 16px;
    }
    .status-row {
      margin-top: 30px;
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      border-top: 1px solid var(--line);
      border-bottom: 1px solid var(--line);
    }
    .stat {
      padding: 18px 12px 18px 0;
      border-right: 1px solid var(--line);
    }
    .stat:last-child { border-right: 0; padding-left: 12px; }
    .stat strong {
      display: block;
      font-size: 28px;
      letter-spacing: -.04em;
    }
    .stat span {
      color: var(--muted);
      font-size: 12px;
    }
    .workspace {
      display: grid;
      gap: 20px;
      animation: rise .7s ease .12s both;
      min-width: 0;
    }
    section {
      background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.025));
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      overflow: hidden;
      min-width: 0;
    }
    .section-head {
      padding: 22px 24px;
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 18px;
      border-bottom: 1px solid var(--line);
    }
    .section-head h3 {
      margin: 0;
      font-size: 18px;
      letter-spacing: -.02em;
    }
    .section-head p {
      margin: 5px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .services {
      padding: 18px 20px 22px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .service {
      padding: 13px 14px;
      border-radius: 18px;
      background: rgba(0,0,0,.18);
      border: 1px solid rgba(255,255,255,.08);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      display: inline-block;
      background: var(--muted);
      box-shadow: 0 0 0 5px rgba(255,255,255,.04);
      margin-right: 8px;
    }
    .ok .dot { background: var(--ok); box-shadow: 0 0 0 5px rgba(101,214,166,.10); }
    .down .dot { background: var(--bad); box-shadow: 0 0 0 5px rgba(255,107,107,.10); }
    .degraded .dot { background: var(--warn); box-shadow: 0 0 0 5px rgba(255,209,102,.10); }
    .service small {
      color: var(--muted);
    }
    .scenario-grid {
      padding: 18px 20px 22px;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .scenario {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 20px;
      padding: 15px;
      background: rgba(0,0,0,.18);
      text-align: left;
      cursor: pointer;
      min-height: 118px;
      transition: transform .2s ease, border-color .2s ease, background .2s ease;
    }
    .scenario:hover {
      transform: translateY(-3px);
      border-color: rgba(255,91,53,.56);
      background: rgba(255,91,53,.08);
    }
    .scenario strong {
      display: block;
      margin-bottom: 9px;
      font-size: 14px;
    }
    .scenario span {
      color: var(--muted);
      line-height: 1.45;
      font-size: 12.5px;
    }
    .architecture {
      padding: 24px;
      min-height: 430px;
      position: relative;
    }
    .flow {
      display: grid;
      grid-template-columns: repeat(5, minmax(92px, 1fr));
      grid-template-rows: repeat(4, 82px);
      gap: 14px;
      position: relative;
    }
    .node {
      border: 1px solid rgba(255,255,255,.12);
      background: rgba(0,0,0,.20);
      border-radius: 18px;
      padding: 12px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      min-width: 0;
      position: relative;
      transition: border-color .2s ease, transform .2s ease;
    }
    .node:hover {
      transform: translateY(-2px);
      border-color: rgba(255,91,53,.6);
    }
    .node b { font-size: 12px; letter-spacing: -.01em; }
    .node small { color: var(--muted); margin-top: 5px; font-size: 11px; }
    .hot::after {
      content: "";
      position: absolute;
      inset: -1px;
      border-radius: inherit;
      border: 1px solid rgba(255,91,53,.8);
      animation: pulse 1.7s ease-in-out infinite;
    }
    .client { grid-column: 1; grid-row: 1; }
    .ui { grid-column: 2; grid-row: 1; }
    .checkout { grid-column: 3; grid-row: 1; }
    .sync { grid-column: 4 / span 2; grid-row: 1; }
    .kafka1 { grid-column: 3; grid-row: 2; }
    .fraud { grid-column: 3; grid-row: 3; }
    .kafka2 { grid-column: 3; grid-row: 4; }
    .notify { grid-column: 4; grid-row: 4; }
    .analytics { grid-column: 5; grid-row: 4; }
    .storage { grid-column: 1 / span 2; grid-row: 4; }
    .signoz { grid-column: 1 / span 2; grid-row: 2 / span 2; }
    .node.sync {
      flex-direction: row;
      align-items: center;
      justify-content: space-around;
      gap: 10px;
    }
    .node.sync span {
      color: var(--muted);
      font-size: 11px;
    }
    .rail {
      position: absolute;
      height: 2px;
      background: linear-gradient(90deg, transparent, rgba(255,91,53,.65), transparent);
      opacity: .75;
      animation: shimmer 2.4s linear infinite;
    }
    .r1 { top: 64px; left: 12%; width: 48%; }
    .r2 { top: 160px; left: 49%; width: 2px; height: 210px; background: linear-gradient(180deg, transparent, rgba(255,91,53,.65), transparent); }
    .r3 { bottom: 66px; right: 8%; width: 35%; }
    .system-map {
      padding: 22px;
      display: grid;
      gap: 18px;
      min-width: 0;
      overflow-x: auto;
      background:
        radial-gradient(circle at 28% 20%, rgba(255,91,53,.13), transparent 28%),
        radial-gradient(circle at 85% 62%, rgba(95,211,255,.10), transparent 28%);
    }
    .map-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .legend-pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 7px 10px;
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 999px;
      background: rgba(0,0,0,.18);
    }
    .legend-line {
      width: 26px;
      height: 2px;
      border-radius: 999px;
      background: rgba(255,255,255,.5);
    }
    .legend-line.http { background: linear-gradient(90deg, #6ea8ff, #b6d0ff); }
    .legend-line.kafka { background: linear-gradient(90deg, #ffb86b, #ff5b35); }
    .legend-line.telemetry { background: linear-gradient(90deg, #65d6a6, #5fd3ff); border-top: 1px dashed rgba(255,255,255,.5); }
    .map-stage {
      position: relative;
      display: grid;
      grid-template-columns: minmax(0, .8fr) minmax(0, 1.15fr) minmax(0, 1fr);
      grid-template-rows: auto auto auto;
      gap: 16px;
      min-height: 620px;
      min-width: 0;
    }
    .map-card {
      border: 1px solid rgba(255,255,255,.10);
      background: linear-gradient(180deg, rgba(10,13,20,.92), rgba(7,9,14,.78));
      border-radius: 24px;
      padding: 16px;
      position: relative;
      overflow: hidden;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
      transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
      min-width: 0;
    }
    .map-card::before {
      content: "";
      position: absolute;
      inset: 0;
      background: linear-gradient(135deg, rgba(255,255,255,.07), transparent 32%);
      pointer-events: none;
    }
    .map-card:hover {
      transform: translateY(-2px);
      border-color: rgba(255,91,53,.45);
    }
    .map-card.active,
    .map-node.active,
    .topic.active,
    .signoz-chip.active,
    .alert-strip.active .alert-row {
      border-color: rgba(255,91,53,.9) !important;
      box-shadow: 0 0 0 1px rgba(255,91,53,.28), 0 18px 48px rgba(255,91,53,.16);
      transform: translateY(-2px) scale(1.01);
    }
    .map-card.capturing {
      border-color: rgba(101,214,166,.9);
      box-shadow: 0 0 0 1px rgba(101,214,166,.22), 0 24px 70px rgba(101,214,166,.15);
    }
    .map-label {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      margin-bottom: 12px;
      position: relative;
      z-index: 1;
    }
    .map-label b {
      font-size: 13px;
      letter-spacing: -.01em;
    }
    .map-label span {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .13em;
    }
    .map-node {
      border: 1px solid rgba(255,255,255,.10);
      border-radius: 18px;
      background: rgba(255,255,255,.045);
      padding: 12px;
      min-height: 72px;
      position: relative;
      z-index: 1;
      transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
    }
    .map-node strong {
      display: block;
      font-size: 13px;
      margin-bottom: 5px;
    }
    .map-node small {
      color: var(--muted);
      font-size: 11px;
      line-height: 1.35;
    }
    .entry-card { grid-column: 1; grid-row: 1; }
    .sync-card { grid-column: 2; grid-row: 1; }
    .kafka-card { grid-column: 1 / span 2; grid-row: 2; }
    .consumer-card { grid-column: 1 / span 2; grid-row: 3; }
    .storage-card { grid-column: 3; grid-row: 1; }
    .observe-card { grid-column: 3; grid-row: 2 / span 2; }
    .node-stack {
      display: grid;
      gap: 10px;
    }
    .node-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .node-grid.two {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
    .entry-path .map-node:not(:last-child)::after {
      content: "↓";
      position: absolute;
      left: 50%;
      bottom: -22px;
      transform: translateX(-50%);
      color: rgba(110,168,255,.85);
      font-weight: 800;
    }
    .checkout-root {
      background: linear-gradient(135deg, rgba(255,91,53,.20), rgba(255,255,255,.045));
    }
    .kafka-bus {
      position: relative;
      z-index: 1;
      border: 1px solid rgba(255,184,107,.40);
      border-radius: 24px;
      padding: 16px;
      background:
        linear-gradient(90deg, rgba(255,184,107,.13), rgba(255,91,53,.11)),
        rgba(0,0,0,.16);
    }
    .bus-title {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .bus-title strong {
      font-size: 17px;
      letter-spacing: -.03em;
    }
    .bus-title span {
      color: var(--muted);
      font-size: 12px;
    }
    .topics {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .topic {
      border: 1px solid rgba(255,184,107,.22);
      border-radius: 16px;
      padding: 11px;
      background: rgba(0,0,0,.22);
      transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
    }
    .topic b {
      display: block;
      font-size: 12px;
      word-break: break-word;
    }
    .topic small {
      color: var(--muted);
      font-size: 10.5px;
    }
    .mini-chart {
      display: flex;
      align-items: end;
      gap: 4px;
      height: 34px;
      margin-top: 10px;
    }
    .mini-chart i {
      display: block;
      width: 12px;
      border-radius: 6px 6px 2px 2px;
      background: linear-gradient(180deg, rgba(95,211,255,.9), rgba(101,214,166,.65));
      opacity: .82;
    }
    .signoz-suite {
      position: relative;
      z-index: 1;
      display: grid;
      gap: 12px;
    }
    .signoz-hero {
      min-height: 112px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      background:
        radial-gradient(circle at 12% 18%, rgba(255,91,53,.28), transparent 34%),
        linear-gradient(135deg, rgba(255,91,53,.14), rgba(95,211,255,.08));
    }
    .sig-eye {
      width: 68px;
      height: 68px;
      border-radius: 24px;
      display: grid;
      place-items: center;
      background: rgba(255,91,53,.16);
      border: 1px solid rgba(255,91,53,.38);
      font-size: 28px;
      box-shadow: 0 14px 34px rgba(255,91,53,.16);
    }
    .signoz-chips {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px;
    }
    .signoz-chip {
      border: 1px solid rgba(255,255,255,.10);
      border-radius: 16px;
      padding: 10px;
      background: rgba(255,255,255,.045);
      min-height: 72px;
      transition: transform .22s ease, border-color .22s ease, box-shadow .22s ease;
    }
    .signoz-chip b {
      display: block;
      font-size: 12px;
      margin-bottom: 4px;
    }
    .signoz-chip small {
      color: var(--muted);
      font-size: 10.5px;
      line-height: 1.35;
    }
    .alert-strip {
      display: grid;
      gap: 8px;
    }
    .alert-row {
      border: 1px solid rgba(255,209,102,.20);
      border-radius: 14px;
      padding: 9px 10px;
      background: rgba(255,209,102,.065);
      color: #f5ead1;
      font-size: 11.5px;
    }
    .capture-panel {
      border: 1px solid rgba(101,214,166,.22);
      border-radius: 16px;
      padding: 11px 12px;
      background: rgba(101,214,166,.06);
      color: #daf8eb;
      font-size: 11.5px;
      line-height: 1.45;
      min-height: 56px;
    }
    .capture-panel b {
      display: block;
      color: #fff;
      font-size: 12px;
      margin-bottom: 3px;
    }
    .mcp-mini {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 9px;
    }
    .mcp-mini .signoz-chip {
      min-height: 64px;
      border-color: rgba(177,139,255,.18);
      background: rgba(177,139,255,.055);
    }
    .telemetry-ribbon {
      position: absolute;
      inset: auto 14px 14px;
      border: 1px dashed rgba(101,214,166,.32);
      border-radius: 18px;
      padding: 9px 11px;
      color: var(--muted);
      font-size: 11px;
      background: rgba(101,214,166,.045);
      z-index: 1;
    }
    .connector {
      position: absolute;
      pointer-events: none;
      opacity: .7;
      z-index: 0;
    }
    .connector.horizontal {
      height: 2px;
      background: linear-gradient(90deg, transparent, rgba(110,168,255,.9), transparent);
      animation: shimmer 2.8s linear infinite;
    }
    .connector.kafka {
      height: 3px;
      background: linear-gradient(90deg, transparent, rgba(255,184,107,.85), rgba(255,91,53,.85), transparent);
      animation: shimmer 2.2s linear infinite;
    }
    .connector.telemetry {
      border-top: 2px dashed rgba(101,214,166,.65);
      animation: shimmer 3.2s linear infinite;
    }
    .c1 { top: 92px; left: 22%; width: 18%; }
    .c2 { top: 250px; left: 24%; width: 33%; }
    .c3 { top: 410px; left: 24%; width: 33%; }
    .c4 { top: 560px; left: 42%; width: 42%; }
    .c5 { top: 304px; left: 61%; width: 24%; transform: rotate(90deg); transform-origin: left center; }
    .flow-readout {
      position: absolute;
      left: 18px;
      right: 18px;
      bottom: 18px;
      z-index: 5;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,.10);
      background: rgba(6,8,12,.78);
      backdrop-filter: blur(12px);
      color: var(--muted);
      font-size: 12px;
    }
    .flow-readout strong {
      color: var(--text);
      font-size: 12px;
    }
    .flow-readout .meter {
      width: 110px;
      height: 5px;
      border-radius: 999px;
      background: rgba(255,255,255,.10);
      overflow: hidden;
      flex: 0 0 auto;
    }
    .flow-readout .meter i {
      display: block;
      width: 0%;
      height: 100%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--accent), var(--ok), var(--accent-2));
    }
    .flow-readout.running .meter i {
      animation: fillMeter 5s ease both;
    }
    .flow-particle {
      position: absolute;
      width: 14px;
      height: 14px;
      border-radius: 999px;
      left: 0;
      top: 0;
      z-index: 20;
      pointer-events: none;
      background: #6ea8ff;
      box-shadow: 0 0 0 7px rgba(110,168,255,.14), 0 0 24px rgba(110,168,255,.72);
    }
    .flow-particle::after {
      content: attr(data-label);
      position: absolute;
      left: 18px;
      top: -5px;
      white-space: nowrap;
      color: #dce9ff;
      font-size: 10px;
      padding: 3px 7px;
      border-radius: 999px;
      background: rgba(6,8,12,.76);
      border: 1px solid rgba(255,255,255,.10);
    }
    .flow-particle.kafka {
      background: #ffb86b;
      box-shadow: 0 0 0 7px rgba(255,184,107,.14), 0 0 24px rgba(255,184,107,.72);
    }
    .flow-particle.telemetry {
      background: var(--ok);
      box-shadow: 0 0 0 7px rgba(101,214,166,.14), 0 0 24px rgba(101,214,166,.72);
    }
    .flow-particle.error {
      background: var(--bad);
      box-shadow: 0 0 0 7px rgba(255,107,107,.14), 0 0 24px rgba(255,107,107,.72);
    }
    .event-log {
      padding: 0;
      max-height: 360px;
      overflow: auto;
    }
    .trace-helper {
      padding: 20px;
      display: grid;
      gap: 16px;
    }
    .trace-empty {
      border: 1px dashed rgba(255,255,255,.16);
      border-radius: 22px;
      padding: 18px;
      color: var(--muted);
      line-height: 1.5;
      background: rgba(0,0,0,.14);
    }
    .trace-summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
    }
    .trace-kv {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 18px;
      padding: 12px;
      background: rgba(0,0,0,.18);
      min-width: 0;
    }
    .trace-kv span {
      display: block;
      color: var(--muted);
      font-size: 10.5px;
      letter-spacing: .12em;
      text-transform: uppercase;
      margin-bottom: 7px;
    }
    .trace-kv strong {
      display: block;
      font-size: 13px;
      word-break: break-word;
    }
    .trace-body {
      display: grid;
      grid-template-columns: minmax(0, .9fr) minmax(0, 1.1fr);
      gap: 14px;
    }
    .trace-card {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 22px;
      padding: 15px;
      background: linear-gradient(180deg, rgba(255,255,255,.045), rgba(255,255,255,.02));
      min-width: 0;
    }
    .trace-card h4 {
      margin: 0 0 10px;
      font-size: 13px;
      letter-spacing: -.01em;
    }
    .trace-card ul {
      margin: 0;
      padding-left: 18px;
      color: #d7dae1;
      font-size: 12.5px;
      line-height: 1.65;
    }
    .trace-card p {
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 12.5px;
    }
    .query-box {
      display: grid;
      gap: 10px;
    }
    .query-box pre {
      margin: 0;
      max-height: 210px;
      overflow: auto;
      border: 1px solid rgba(95,211,255,.16);
      border-radius: 18px;
      padding: 13px;
      background: rgba(0,0,0,.28);
      color: #dff6ff;
      font-size: 11.5px;
      line-height: 1.5;
      white-space: pre-wrap;
    }
    .helper-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }
    .button.small {
      padding: 8px 11px;
      font-size: 12px;
    }
    .button.ghost {
      background: rgba(255,255,255,.035);
    }
    .ai-layer {
      padding: 20px;
      display: grid;
      gap: 16px;
    }
    .ai-flow {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      align-items: stretch;
    }
    .ai-node {
      border: 1px solid rgba(177,139,255,.18);
      border-radius: 22px;
      padding: 16px;
      background:
        radial-gradient(circle at 18% 18%, rgba(177,139,255,.16), transparent 34%),
        rgba(0,0,0,.18);
      min-height: 120px;
      position: relative;
      overflow: hidden;
    }
    .ai-node::after {
      content: "→";
      position: absolute;
      right: -9px;
      top: 50%;
      transform: translateY(-50%);
      color: rgba(177,139,255,.65);
      font-size: 28px;
      z-index: 2;
    }
    .ai-node:last-child::after { display: none; }
    .ai-node span {
      display: inline-flex;
      margin-bottom: 12px;
      color: #dcd2ff;
      font-size: 11px;
      letter-spacing: .14em;
      text-transform: uppercase;
    }
    .ai-node strong {
      display: block;
      font-size: 16px;
      margin-bottom: 8px;
      letter-spacing: -.02em;
    }
    .ai-node p {
      margin: 0;
      color: var(--muted);
      font-size: 12.5px;
      line-height: 1.5;
    }
    .prompt-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .prompt-card {
      border: 1px solid rgba(255,255,255,.09);
      border-radius: 18px;
      padding: 13px;
      background: rgba(0,0,0,.18);
      color: #dfe6f2;
      font-size: 12px;
      line-height: 1.45;
    }
    .mcp-status {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .mcp-status span {
      border: 1px solid rgba(101,214,166,.22);
      border-radius: 999px;
      padding: 7px 10px;
      background: rgba(101,214,166,.055);
      color: #d9f8eb;
    }
    .event {
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 12px;
      padding: 15px 20px;
      border-top: 1px solid rgba(255,255,255,.08);
      color: #d9dce2;
      font-size: 13px;
    }
    .event:first-child { border-top: 0; }
    .event time {
      color: var(--muted);
      font-variant-numeric: tabular-nums;
    }
    .event code {
      color: var(--accent-2);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }
    @keyframes rise {
      from { opacity: 0; transform: translateY(16px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse {
      0%, 100% { opacity: .15; transform: scale(1); }
      50% { opacity: .75; transform: scale(1.035); }
    }
    @keyframes shimmer {
      from { filter: hue-rotate(0deg); opacity: .35; }
      50% { opacity: .95; }
      to { filter: hue-rotate(30deg); opacity: .35; }
    }
    @keyframes fillMeter {
      from { width: 0%; }
      72% { width: 88%; }
      to { width: 100%; }
    }
    @media (max-width: 1180px) {
      header, main { padding-left: 18px; padding-right: 18px; }
      main { grid-template-columns: 1fr; }
      .intro { position: relative; top: auto; }
      .intro h2 { max-width: 900px; }
      .workspace { width: 100%; }
    }
    @media (max-width: 980px) {
      .flow { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: none; }
      .node { grid-column: auto !important; grid-row: auto !important; min-height: 78px; }
      .rail { display: none; }
      .map-stage { grid-template-columns: 1fr; min-height: auto; }
      .entry-card, .sync-card, .kafka-card, .consumer-card, .storage-card, .observe-card {
        grid-column: auto;
        grid-row: auto;
      }
      .connector { display: none; }
    }
    @media (max-width: 620px) {
      header { align-items: flex-start; flex-direction: column; }
      .scenario-grid, .services, .status-row { grid-template-columns: 1fr; }
      .node-grid, .node-grid.two, .topics, .signoz-chips { grid-template-columns: 1fr; }
      .trace-summary, .trace-body { grid-template-columns: 1fr; }
      .ai-flow, .prompt-grid, .mcp-mini { grid-template-columns: 1fr; }
      .ai-node::after { display: none; }
      .stat { border-right: 0; border-bottom: 1px solid var(--line); }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <div class="mark">OA</div>
      <div>
        <h1>ObserveAI</h1>
        <p>Local observability control room</p>
      </div>
    </div>
    <div class="top-actions">
      <a class="button" href="http://127.0.0.1:8080" target="_blank" rel="noreferrer">Open SigNoz</a>
      <button class="button primary" id="refresh">Refresh status</button>
    </div>
  </header>

  <main>
    <aside class="intro">
      <div class="eyebrow">OpenTelemetry · Kafka · SigNoz</div>
      <h2>Trigger the system. Watch the evidence.</h2>
      <p class="copy">
        Fire checkout, payment, Kafka, fraud, notification, analytics, database, and DLQ scenarios from one surface.
        Then inspect the traces, dashboards, and alerts in SigNoz.
      </p>
      <div class="status-row">
        <div class="stat"><strong id="ok-count">—</strong><span>healthy services</span></div>
        <div class="stat"><strong id="scenario-count">12</strong><span>demo scenarios</span></div>
        <div class="stat"><strong id="last-code">—</strong><span>last response</span></div>
      </div>
    </aside>

    <div class="workspace">
      <section>
        <div class="section-head">
          <div>
            <h3>Service status</h3>
            <p>Health checks through the UI proxy.</p>
          </div>
        </div>
        <div class="services" id="services"></div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h3>Scenario launcher</h3>
            <p>Each click creates fresh telemetry for SigNoz.</p>
          </div>
          <button class="button" id="seed-cart">Seed cart</button>
        </div>
        <div class="scenario-grid" id="scenarios"></div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h3>Architecture map</h3>
            <p>HTTP checkout path, Kafka event bus, async consumers, and SigNoz observability plane.</p>
          </div>
        </div>
        <div class="system-map">
          <div class="map-legend">
            <span class="legend-pill"><i class="legend-line http"></i>HTTP sync calls</span>
            <span class="legend-pill"><i class="legend-line kafka"></i>Kafka / Redpanda events</span>
            <span class="legend-pill"><i class="legend-line telemetry"></i>OTLP telemetry export</span>
          </div>

          <div class="map-stage">
            <div class="connector horizontal c1"></div>
            <div class="connector kafka c2"></div>
            <div class="connector kafka c3"></div>
            <div class="connector telemetry c4"></div>
            <div class="connector telemetry c5"></div>
            <div class="flow-readout" id="flow-readout">
              <span><strong>Flow simulator</strong> Click a scenario to animate request, Kafka, and telemetry capture.</span>
              <span class="meter"><i></i></span>
            </div>

            <div class="map-card entry-card" data-node="entry">
              <div class="map-label"><b>Entry path</b><span>user → app</span></div>
              <div class="node-stack entry-path">
                <div class="map-node" data-node="browser"><strong>Browser</strong><small>You open ObserveAI and trigger experiments.</small></div>
                <div class="map-node" data-node="ui"><strong>ui-service</strong><small>Scenario launcher, status proxy, and trace producer.</small></div>
                <div class="map-node checkout-root" data-node="checkout"><strong>checkout-service</strong><small>Root workflow that calls sync services and publishes events.</small></div>
              </div>
            </div>

            <div class="map-card sync-card" data-node="sync">
              <div class="map-label"><b>Synchronous dependencies</b><span>request path</span></div>
              <div class="node-grid">
                <div class="map-node" data-node="cart"><strong>cart-service</strong><small>Cart lookup and cart seed operations.</small></div>
                <div class="map-node" data-node="inventory"><strong>inventory-service</strong><small>Stock reservation and out-of-stock failures.</small></div>
                <div class="map-node" data-node="payment"><strong>payment-service</strong><small>Slow payments, failures, and provider timeouts.</small></div>
              </div>
            </div>

            <div class="map-card storage-card" data-node="storage">
              <div class="map-label"><b>State layer</b><span>data stores</span></div>
              <div class="node-stack">
                <div class="map-node" data-node="postgres"><strong>Postgres</strong><small>Orders, inventory state, analytics events, slow query scenarios.</small></div>
                <div class="map-node" data-node="redis"><strong>Redis</strong><small>Cart/session style cache for fast reads.</small></div>
                <div class="mini-chart" aria-label="storage activity">
                  <i style="height: 38%"></i><i style="height: 64%"></i><i style="height: 44%"></i><i style="height: 82%"></i><i style="height: 58%"></i>
                </div>
              </div>
            </div>

            <div class="map-card kafka-card" data-node="kafka">
              <div class="map-label"><b>Event streaming backbone</b><span>async path</span></div>
              <div class="kafka-bus">
                <div class="bus-title">
                  <strong>Redpanda / Kafka-compatible bus</strong>
                  <span>producer latency · consumer lag · DLQ</span>
                </div>
                <div class="topics">
                  <div class="topic" data-node="fraud-topic"><b>fraud.check.requested</b><small>checkout produces fraud work</small></div>
                  <div class="topic" data-node="fraud-completed"><b>fraud.check.completed</b><small>AI fraud result events</small></div>
                  <div class="topic" data-node="dlq"><b>fraud.check.dlq</b><small>poison messages and retries</small></div>
                </div>
              </div>
            </div>

            <div class="map-card consumer-card" data-node="consumers">
              <div class="map-label"><b>Async consumers</b><span>event handlers</span></div>
              <div class="node-grid">
                <div class="map-node" data-node="fraud"><strong>ai-fraud-service</strong><small>Rule-based inference, risk score, model latency, failures.</small></div>
                <div class="map-node" data-node="notification"><strong>notification-service</strong><small>Email simulation, provider failure, slow consumer scenarios.</small></div>
                <div class="map-node" data-node="analytics"><strong>analytics-service</strong><small>Business event processing and analytics lag.</small></div>
              </div>
            </div>

            <div class="map-card observe-card" data-node="signoz">
              <div class="map-label"><b>Observability plane</b><span>evidence</span></div>
              <div class="signoz-suite">
                <div class="map-node signoz-hero" data-node="otel">
                  <div>
                    <strong>OpenTelemetry Collector → SigNoz</strong>
                    <small>Every service exports spans, logs, and metrics through OTLP.</small>
                  </div>
                  <div class="sig-eye">◉</div>
                </div>
                <div class="signoz-chips">
                  <div class="signoz-chip" data-node="traces"><b>Traces</b><small>Follow one checkout across HTTP, Kafka, AI, and storage.</small></div>
                  <div class="signoz-chip" data-node="logs"><b>Logs</b><small>Error messages, scenario names, order IDs, and failures.</small></div>
                  <div class="signoz-chip" data-node="metrics"><b>Metrics</b><small>p50/p90/p99 latency, request counts, error rates.</small></div>
                  <div class="signoz-chip" data-node="dashboards"><b>Dashboards</b><small>Checkout, Kafka, AI services, and business health panels.</small></div>
                </div>
                <div class="alert-strip" data-node="alerts">
                  <div class="alert-row">Alert: checkout p99 latency high</div>
                  <div class="alert-row">Alert: Kafka consumer lag / DLQ messages</div>
                  <div class="alert-row">Alert: AI fraud inference slow or failing</div>
                </div>
                <div class="capture-panel" id="capture-panel">
                  <b>SigNoz capture</b>
                  Waiting for a scenario. When you trigger one, telemetry pulses flow into traces, metrics, dashboards, logs, and alerts.
                </div>
                <div class="mcp-mini">
                  <div class="signoz-chip" data-node="mcp"><b>SigNoz MCP</b><small>Exposes telemetry tools for AI investigation.</small></div>
                  <div class="signoz-chip" data-node="codex"><b>Codex</b><small>Queries traces, logs, metrics, dashboards, and alerts.</small></div>
                </div>
              </div>
              <div class="telemetry-ribbon">OTLP signals → SigNoz evidence → MCP tools → Codex investigation</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h3>Trace helper</h3>
            <p>After a scenario runs, use this to investigate the exact evidence in SigNoz.</p>
          </div>
          <a class="button" href="http://127.0.0.1:8080" target="_blank" rel="noreferrer">Open SigNoz</a>
        </div>
        <div class="trace-helper" id="trace-helper">
          <div class="trace-empty">
            Run a scenario to generate an order id, investigation checklist, and a copyable ClickHouse query for SigNoz.
          </div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h3>AI investigation layer</h3>
            <p>Codex connects to SigNoz through MCP. The browser never sees your API key.</p>
          </div>
          <a class="button" href="http://localhost:8000/livez" target="_blank" rel="noreferrer">MCP health</a>
        </div>
        <div class="ai-layer">
          <div class="mcp-status">
            <span>SigNoz MCP: http://localhost:8000/mcp</span>
            <span>Codex MCP server: signoz</span>
            <span>Tools: traces · logs · metrics · dashboards · alerts</span>
          </div>
          <div class="ai-flow">
            <div class="ai-node" data-node="signoz">
              <span>Evidence store</span>
              <strong>SigNoz</strong>
              <p>Stores ObserveAI traces, logs, metrics, dashboards, alerts, and service topology.</p>
            </div>
            <div class="ai-node" data-node="mcp">
              <span>Access layer</span>
              <strong>SigNoz MCP</strong>
              <p>Turns SigNoz capabilities into tools an AI assistant can call safely.</p>
            </div>
            <div class="ai-node" data-node="codex">
              <span>Investigator</span>
              <strong>Codex</strong>
              <p>Uses MCP to list services, inspect traces, suggest dashboards, and reason about incidents.</p>
            </div>
          </div>
          <div class="trace-card">
            <h4>Try these in Codex</h4>
            <div class="prompt-grid">
              <div class="prompt-card">Using SigNoz MCP, list the ObserveAI services currently sending telemetry.</div>
              <div class="prompt-card">Using SigNoz MCP, investigate the latest payment_slow scenario and identify the bottleneck span.</div>
              <div class="prompt-card">Using SigNoz MCP, check for fraud.check.dlq or poison_message activity in the last hour.</div>
              <div class="prompt-card">Using SigNoz MCP, create an ObserveAI AI & Payments dashboard with payment and fraud latency panels.</div>
            </div>
          </div>
        </div>
      </section>

      <section>
        <div class="section-head">
          <div>
            <h3>Event trail</h3>
            <p>Recent UI-triggered runs.</p>
          </div>
        </div>
        <div class="event-log" id="events"></div>
      </section>
    </div>
  </main>

  <script>
    const scenarioDetails = {
      normal: "Happy path checkout and fraud queue.",
      payment_slow: "Payment latency spike.",
      payment_fail: "Expected payment failure.",
      provider_timeout: "Provider timeout-style failure.",
      inventory_fail: "Out-of-stock path.",
      fraud_ai_slow: "AI fraud inference latency.",
      kafka_consumer_slow: "Kafka consumer lag.",
      poison_message: "Retries and DLQ publish.",
      notification_slow: "Notification consumer delay.",
      notification_fail: "Notification provider failure.",
      analytics_slow: "Analytics consumer delay.",
      db_slow: "Postgres slow query."
    };
    const scenarioNodes = {
      normal: ["entry", "checkout", "kafka", "fraud-topic", "fraud", "notification", "analytics", "signoz", "traces", "metrics", "dashboards", "mcp", "codex"],
      payment_slow: ["checkout", "payment", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"],
      payment_fail: ["checkout", "payment", "signoz", "logs", "traces", "alerts", "mcp", "codex"],
      provider_timeout: ["checkout", "payment", "signoz", "logs", "metrics", "alerts", "mcp", "codex"],
      inventory_fail: ["checkout", "inventory", "signoz", "logs", "traces", "mcp", "codex"],
      fraud_ai_slow: ["checkout", "kafka", "fraud-topic", "fraud", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"],
      kafka_consumer_slow: ["checkout", "kafka", "fraud-topic", "fraud", "signoz", "metrics", "dashboards", "alerts", "mcp", "codex"],
      poison_message: ["checkout", "kafka", "fraud-topic", "fraud", "dlq", "signoz", "logs", "alerts", "mcp", "codex"],
      notification_slow: ["kafka", "fraud-completed", "notification", "signoz", "traces", "dashboards", "mcp", "codex"],
      notification_fail: ["kafka", "fraud-completed", "notification", "signoz", "logs", "alerts", "mcp", "codex"],
      analytics_slow: ["kafka", "fraud-completed", "analytics", "signoz", "metrics", "dashboards", "mcp", "codex"],
      db_slow: ["checkout", "postgres", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"]
    };
    const flowStories = {
      normal: {
        readout: "Happy path: HTTP checkout completes, Kafka fans out fraud results, and SigNoz captures normal traces/metrics.",
        capture: "Healthy baseline captured: checkout trace, Kafka publish/consume spans, normal latency, and business events.",
        request: ["browser", "ui", "checkout", "cart", "checkout", "inventory", "checkout", "payment", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "fraud-completed", "notification", "fraud-completed", "analytics"],
        telemetry: ["checkout", "otel", "signoz", "traces", "metrics", "dashboards", "mcp", "codex"]
      },
      payment_slow: {
        readout: "Payment slow: the request stalls in payment-service while telemetry reaches SigNoz as high p99 latency.",
        capture: "SigNoz catches slow payment spans, checkout p99 movement, and dashboard/alert evidence.",
        request: ["browser", "ui", "checkout", "payment", "checkout"],
        telemetry: ["payment", "otel", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"]
      },
      payment_fail: {
        readout: "Payment failure: checkout receives a failed payment response and SigNoz captures errors plus logs.",
        capture: "SigNoz catches payment error spans, failure logs, and alert-worthy checkout failures.",
        request: ["browser", "ui", "checkout", "payment", "checkout"],
        telemetry: ["payment", "otel", "signoz", "traces", "logs", "alerts", "mcp", "codex"],
        error: true
      },
      provider_timeout: {
        readout: "Provider timeout: payment waits on a simulated provider timeout and observability records the timeout path.",
        capture: "SigNoz catches provider timeout logs, slow/error spans, and alert evidence for payment reliability.",
        request: ["browser", "ui", "checkout", "payment", "checkout"],
        telemetry: ["payment", "otel", "signoz", "logs", "metrics", "alerts", "mcp", "codex"],
        error: true
      },
      inventory_fail: {
        readout: "Inventory failure: inventory returns out-of-stock; SigNoz shows this as a business failure path.",
        capture: "SigNoz catches the inventory branch and logs, but this is business failure rather than infra outage.",
        request: ["browser", "ui", "checkout", "inventory", "checkout"],
        telemetry: ["inventory", "otel", "signoz", "traces", "logs", "mcp", "codex"]
      },
      fraud_ai_slow: {
        readout: "AI fraud slow: checkout queues work, then the async fraud consumer becomes the bottleneck.",
        capture: "SigNoz catches fraud inference latency, Kafka consumer spans, and AI dashboard movement.",
        request: ["browser", "ui", "checkout", "payment", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "fraud-completed"],
        telemetry: ["fraud", "otel", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"]
      },
      kafka_consumer_slow: {
        readout: "Kafka lag: events enter the bus faster than the fraud consumer can process them.",
        capture: "SigNoz catches consumer lag signals, delayed fraud spans, dashboards, and lag alerts.",
        request: ["browser", "ui", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud"],
        telemetry: ["kafka", "otel", "signoz", "metrics", "dashboards", "alerts", "mcp", "codex"]
      },
      poison_message: {
        readout: "Poison message: fraud consumer retries and publishes to DLQ; SigNoz captures the failure chain.",
        capture: "SigNoz catches retry/error logs, DLQ publish spans, and alert-worthy poison-message behavior.",
        request: ["browser", "ui", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "dlq"],
        telemetry: ["fraud", "otel", "signoz", "logs", "alerts", "mcp", "codex"],
        error: true
      },
      notification_slow: {
        readout: "Notification slow: fraud completes, then notification processing delays downstream work.",
        capture: "SigNoz catches notification consumer delay and downstream dashboard evidence.",
        request: ["browser", "ui", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "fraud-completed", "notification"],
        telemetry: ["notification", "otel", "signoz", "traces", "dashboards", "mcp", "codex"]
      },
      notification_fail: {
        readout: "Notification failure: the user checkout succeeds, but downstream notification records provider failure.",
        capture: "SigNoz catches notification provider errors without confusing them with checkout failure.",
        request: ["browser", "ui", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "fraud-completed", "notification"],
        telemetry: ["notification", "otel", "signoz", "logs", "alerts", "mcp", "codex"],
        error: true
      },
      analytics_slow: {
        readout: "Analytics slow: async business event processing lags after fraud completion.",
        capture: "SigNoz catches analytics consumer latency and business-event processing delay.",
        request: ["browser", "ui", "checkout"],
        kafka: ["checkout", "kafka", "fraud-topic", "fraud", "fraud-completed", "analytics"],
        telemetry: ["analytics", "otel", "signoz", "metrics", "dashboards", "mcp", "codex"]
      },
      db_slow: {
        readout: "Database slow: checkout spends time writing/reading Postgres; SigNoz captures DB span latency.",
        capture: "SigNoz catches slow Postgres spans, checkout p99 movement, and database dashboard evidence.",
        request: ["browser", "ui", "checkout", "postgres", "checkout"],
        telemetry: ["postgres", "otel", "signoz", "traces", "metrics", "dashboards", "alerts", "mcp", "codex"]
      }
    };
    const investigationGuides = {
      normal: {
        focus: "Healthy baseline trace across checkout, Kafka, fraud, notification, and analytics.",
        dashboard: "System Overview / Checkout Health",
        alert: "No alert expected. Use this as baseline noise level.",
        look: ["Traces → checkout-service", "Kafka producer and consumer spans", "AI fraud decision logs", "Metrics baseline for request count and p99"],
        services: ["checkout-service", "ai-fraud-service", "notification-service", "analytics-service"]
      },
      payment_slow: {
        focus: "Payment-service latency should dominate the checkout trace.",
        dashboard: "Payment Health",
        alert: "payment p99 > 800ms or checkout p99 > 1s",
        look: ["Traces → checkout-service → payment-service span", "Metrics → p99 duration by service", "Logs containing payment_slow", "Dashboard panel: payment latency"],
        services: ["checkout-service", "payment-service"]
      },
      payment_fail: {
        focus: "Payment returns failure and checkout records an expected failed path.",
        dashboard: "Checkout Health / Payment Health",
        alert: "payment failure rate > 5%",
        look: ["Logs for payment failure", "Trace error status on payment-service", "Checkout response status", "Payment failure counter"],
        services: ["checkout-service", "payment-service"]
      },
      provider_timeout: {
        focus: "External provider timeout simulation from payment-service.",
        dashboard: "Payment Health",
        alert: "payment timeout logs > threshold",
        look: ["Logs containing provider timeout", "Payment span duration and error", "Checkout failure propagation", "Alert query for timeout count"],
        services: ["checkout-service", "payment-service"]
      },
      inventory_fail: {
        focus: "Out-of-stock business failure, not necessarily infra failure.",
        dashboard: "Checkout Health",
        alert: "Usually business metric, not pager alert.",
        look: ["Inventory-service trace branch", "HTTP 409 style response", "Logs for out_of_stock", "Checkout failure reason"],
        services: ["checkout-service", "inventory-service"]
      },
      fraud_ai_slow: {
        focus: "Async AI fraud inference latency after checkout has queued Kafka work.",
        dashboard: "Fraud Pipeline / AI Services",
        alert: "fraud inference p99 > 500ms",
        look: ["Kafka consumer span in ai-fraud-service", "fraud.inference duration", "Risk score logs", "AI services dashboard"],
        services: ["checkout-service", "ai-fraud-service"]
      },
      kafka_consumer_slow: {
        focus: "Kafka consumer lag grows because fraud consumer processes slowly.",
        dashboard: "Fraud Pipeline",
        alert: "fraud consumer lag > threshold",
        look: ["Kafka publish span from checkout", "ai-fraud-service consumer latency", "consumer lag dashboard panel", "Fraud topic backlog evidence"],
        services: ["checkout-service", "ai-fraud-service"]
      },
      poison_message: {
        focus: "Poison event causes retries and DLQ publish.",
        dashboard: "Fraud Pipeline",
        alert: "DLQ messages > 0 or retry count > threshold",
        look: ["Logs for poison message", "DLQ publish span", "fraud.check.dlq topic", "Exception/error status in ai-fraud-service"],
        services: ["checkout-service", "ai-fraud-service"]
      },
      notification_slow: {
        focus: "Checkout succeeds, then downstream notification consumer is slow.",
        dashboard: "Downstream Consumers",
        alert: "notification consumer latency high",
        look: ["notification-service consumer span", "fraud.check.completed event path", "Notification DB write latency", "Downstream consumer dashboard"],
        services: ["notification-service", "ai-fraud-service"]
      },
      notification_fail: {
        focus: "Checkout succeeds but notification provider simulation fails downstream.",
        dashboard: "Downstream Consumers",
        alert: "notification provider failures > threshold",
        look: ["notification-service error logs", "Provider failure span", "Business impact: order succeeded but notification degraded", "Alert query for notification failures"],
        services: ["notification-service", "ai-fraud-service"]
      },
      analytics_slow: {
        focus: "Analytics consumer is slow after fraud completion.",
        dashboard: "Downstream Consumers",
        alert: "analytics consumer latency high",
        look: ["analytics-service consumer span", "analytics DB write span", "Processing delay metrics", "Downstream Consumers dashboard"],
        services: ["analytics-service", "ai-fraud-service"]
      },
      db_slow: {
        focus: "Postgres step slows checkout and should appear as DB span latency.",
        dashboard: "Database and Redis Health",
        alert: "Postgres span p99 > 500ms",
        look: ["Checkout trace → Postgres span", "DB slow query marker", "Database dashboard p99", "Checkout p99 impact"],
        services: ["checkout-service"]
      }
    };
    const scenarios = Object.keys(scenarioDetails);
    const servicesEl = document.querySelector("#services");
    const scenariosEl = document.querySelector("#scenarios");
    const eventsEl = document.querySelector("#events");
    const okCountEl = document.querySelector("#ok-count");
    const lastCodeEl = document.querySelector("#last-code");
    const mapStageEl = document.querySelector(".map-stage");
    const flowReadoutEl = document.querySelector("#flow-readout");
    const capturePanelEl = document.querySelector("#capture-panel");
    const traceHelperEl = document.querySelector("#trace-helper");

    function pretty(name) {
      return name.replaceAll("_", " ").replace(/\\b\\w/g, c => c.toUpperCase());
    }

    function addEvent(label, detail, code = "—") {
      const row = document.createElement("div");
      row.className = "event";
      const now = new Date();
      row.innerHTML = `<time>${now.toLocaleTimeString()}</time><div><code>${label}</code><br>${detail}</div>`;
      eventsEl.prepend(row);
      lastCodeEl.textContent = code;
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, char => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;"
      }[char]));
    }

    function queryForRun(scenario, orderId, services) {
      const serviceList = services.map(service => `'${service}'`).join(", ");
      const orderFilter = orderId && !String(orderId).startsWith("see ")
        ? `\\n  AND (attributes_string['order_id'] = '${orderId}' OR trace_id IN (
    SELECT trace_id
    FROM signoz_traces.distributed_signoz_index_v3
    WHERE timestamp >= now() - INTERVAL 30 MINUTE
      AND attributes_string['order_id'] = '${orderId}'
  ))`
        : "";
      return `SELECT
  timestamp,
  trace_id,
  serviceName,
  name,
  duration_nano / 1000000 AS duration_ms,
  status_code,
  has_error,
  attributes_string['scenario'] AS scenario,
  attributes_string['order_id'] AS order_id
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 30 MINUTE
  AND serviceName IN (${serviceList})
  AND (attributes_string['scenario'] = '${scenario}' OR attributes_string['order_id'] = '${orderId}' OR name ILIKE '%${scenario}%')${orderFilter}
ORDER BY timestamp DESC
LIMIT 100;`;
    }

    function renderTraceHelper({scenario, orderId, statusCode, expected}) {
      const guide = investigationGuides[scenario] || investigationGuides.normal;
      const query = queryForRun(scenario, orderId, guide.services);
      traceHelperEl.innerHTML = `
        <div class="trace-summary">
          <div class="trace-kv"><span>Scenario</span><strong>${escapeHtml(pretty(scenario))}</strong></div>
          <div class="trace-kv"><span>Order id</span><strong>${escapeHtml(orderId || "not returned")}</strong></div>
          <div class="trace-kv"><span>Response</span><strong>${escapeHtml(statusCode || "—")}</strong></div>
        </div>
        <div class="trace-body">
          <div class="trace-card">
            <h4>Investigation path</h4>
            <p>${escapeHtml(guide.focus)}</p>
            <ul>${guide.look.map(item => `<li>${escapeHtml(item)}</li>`).join("")}</ul>
          </div>
          <div class="trace-card query-box">
            <h4>Copy into SigNoz ClickHouse Query</h4>
            <pre id="trace-query">${escapeHtml(query)}</pre>
            <div class="helper-actions">
              <button class="button small primary" id="copy-trace-query">Copy query</button>
              <a class="button small ghost" href="http://127.0.0.1:8080" target="_blank" rel="noreferrer">Open SigNoz</a>
            </div>
          </div>
        </div>
        <div class="trace-body">
          <div class="trace-card"><h4>Dashboard</h4><p>${escapeHtml(guide.dashboard)}</p></div>
          <div class="trace-card"><h4>Alert candidate</h4><p>${escapeHtml(guide.alert)}</p><p>${escapeHtml(expected || "")}</p></div>
        </div>
      `;
      document.querySelector("#copy-trace-query")?.addEventListener("click", async () => {
        await navigator.clipboard.writeText(query);
        addEvent("trace-helper", "Copied SigNoz ClickHouse query.", "copied");
      });
    }

    function highlightScenario(name) {
      document.querySelectorAll("[data-node]").forEach(el => el.classList.remove("active"));
      const nodes = scenarioNodes[name] || [];
      for (const node of nodes) {
        document.querySelectorAll(`[data-node="${node}"]`).forEach(el => el.classList.add("active"));
      }
      window.clearTimeout(window.__observeAiHighlightTimer);
      window.__observeAiHighlightTimer = window.setTimeout(() => {
        document.querySelectorAll("[data-node]").forEach(el => el.classList.remove("active"));
      }, 5200);
    }

    function centerOfNode(nodeName) {
      const el = document.querySelector(`[data-node="${nodeName}"]`);
      if (!el || !mapStageEl) return null;
      const stageBox = mapStageEl.getBoundingClientRect();
      const box = el.getBoundingClientRect();
      return {
        x: box.left - stageBox.left + box.width / 2,
        y: box.top - stageBox.top + box.height / 2
      };
    }

    function runPacket(kind, path, label, delay = 0) {
      const points = path.map(centerOfNode).filter(Boolean);
      if (points.length < 2 || !mapStageEl) return;
      const particle = document.createElement("div");
      particle.className = `flow-particle ${kind}`;
      particle.dataset.label = label;
      mapStageEl.appendChild(particle);
      const keyframes = points.map((point, index) => ({
        transform: `translate(${point.x - 7}px, ${point.y - 7}px) scale(${index === points.length - 1 ? 1.18 : 1})`,
        opacity: index === 0 ? .25 : 1,
        offset: index / (points.length - 1)
      }));
      const duration = Math.max(1500, Math.min(5200, points.length * 470));
      const animation = particle.animate(keyframes, {
        delay,
        duration,
        easing: "cubic-bezier(.16, 1, .3, 1)",
        fill: "forwards"
      });
      animation.finished.then(() => {
        particle.animate([{opacity: 1}, {opacity: 0, transform: keyframes.at(-1).transform + " scale(.6)"}], {
          duration: 260,
          fill: "forwards"
        }).finished.then(() => particle.remove());
      }).catch(() => particle.remove());
    }

    function simulateScenarioFlow(name) {
      document.querySelectorAll(".flow-particle").forEach(el => el.remove());
      document.querySelectorAll(".capturing").forEach(el => el.classList.remove("capturing"));
      window.clearTimeout(window.__observeAiCaptureTimer);
      const story = flowStories[name] || flowStories.normal;
      highlightScenario(name);
      flowReadoutEl.classList.remove("running");
      void flowReadoutEl.offsetWidth;
      flowReadoutEl.classList.add("running");
      flowReadoutEl.querySelector("span").innerHTML = `<strong>Animating ${pretty(name)}</strong> ${story.readout}`;
      capturePanelEl.innerHTML = `<b>SigNoz capture</b> Listening for telemetry from this scenario…`;
      runPacket(story.error ? "error" : "", story.request || [], "HTTP", 0);
      if (story.kafka) runPacket("kafka", story.kafka, "Kafka", 650);
      runPacket("telemetry", story.telemetry || ["checkout", "otel", "signoz", "mcp", "codex"], "OTLP", 1100);
      window.__observeAiCaptureTimer = window.setTimeout(() => {
        document.querySelector('[data-node="signoz"]')?.classList.add("capturing");
        capturePanelEl.innerHTML = `<b>SigNoz captured</b> ${story.capture}`;
      }, 2200);
    }

    async function refreshServices() {
      servicesEl.innerHTML = "";
      const res = await fetch("/api/services");
      const data = await res.json();
      const okCount = data.services.filter(s => s.status === "ok").length;
      okCountEl.textContent = `${okCount}/${data.services.length}`;
      for (const service of data.services) {
        const item = document.createElement("div");
        item.className = `service ${service.status}`;
        item.innerHTML = `
          <div><span class="dot"></span>${service.name}</div>
          <small>${service.latency_ms ?? "—"} ms</small>
        `;
        servicesEl.appendChild(item);
      }
    }

    async function triggerScenario(name) {
      simulateScenarioFlow(name);
      addEvent(name, "Triggering scenario…");
      const res = await fetch("/api/scenarios", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({scenario: name, use_cart: false})
      });
      const data = await res.json();
      const order = data.response?.order_id || data.response?.detail?.reason || "see response";
      addEvent(name, `${data.expected || "Scenario completed."} Result: ${order}`, data.status_code || res.status);
      renderTraceHelper({
        scenario: name,
        orderId: order,
        statusCode: data.status_code || res.status,
        expected: data.expected
      });
    }

    async function seedCart() {
      const res = await fetch("/api/cart/seed", {method: "POST"});
      const data = await res.json();
      addEvent("cart", `Seeded cart for ${data.user_id}`, res.status);
    }

    function renderScenarios() {
      scenariosEl.innerHTML = "";
      for (const name of scenarios) {
        const button = document.createElement("button");
        button.className = "scenario";
        button.innerHTML = `<strong>${pretty(name)}</strong><span>${scenarioDetails[name]}</span>`;
        button.addEventListener("click", () => triggerScenario(name));
        scenariosEl.appendChild(button);
      }
    }

    document.querySelector("#refresh").addEventListener("click", refreshServices);
    document.querySelector("#seed-cart").addEventListener("click", seedCart);
    renderScenarios();
    refreshServices();
    addEvent("ready", "ObserveAI UI loaded. Trigger a scenario and open SigNoz.");
    setInterval(refreshServices, 15000);
  </script>
</body>
</html>
"""
