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
    }
    section {
      background: linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.025));
      border: 1px solid var(--line);
      border-radius: 28px;
      box-shadow: var(--shadow);
      overflow: hidden;
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
    .event-log {
      padding: 0;
      max-height: 360px;
      overflow: auto;
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
    @media (max-width: 980px) {
      header, main { padding-left: 18px; padding-right: 18px; }
      main { grid-template-columns: 1fr; }
      .intro { position: relative; top: auto; }
      .flow { grid-template-columns: repeat(2, minmax(0, 1fr)); grid-template-rows: none; }
      .node { grid-column: auto !important; grid-row: auto !important; min-height: 78px; }
      .rail { display: none; }
    }
    @media (max-width: 620px) {
      header { align-items: flex-start; flex-direction: column; }
      .scenario-grid, .services, .status-row { grid-template-columns: 1fr; }
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
      <a class="button" href="http://localhost:8080" target="_blank" rel="noreferrer">Open SigNoz</a>
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
            <p>Synchronous checkout, async Kafka fan-out, and observability export.</p>
          </div>
        </div>
        <div class="architecture">
          <div class="rail r1"></div>
          <div class="rail r2"></div>
          <div class="rail r3"></div>
          <div class="flow">
            <div class="node client"><b>Browser</b><small>you</small></div>
            <div class="node ui hot"><b>ui-service</b><small>scenario proxy</small></div>
            <div class="node checkout hot"><b>checkout</b><small>workflow root</small></div>
            <div class="node sync"><span>cart</span><span>inventory</span><span>payment</span><span>postgres</span></div>
            <div class="node kafka1 hot"><b>fraud.check.requested</b><small>Redpanda topic</small></div>
            <div class="node fraud hot"><b>ai-fraud-service</b><small>rules inference</small></div>
            <div class="node kafka2 hot"><b>fraud.check.completed / dlq</b><small>Kafka fan-out</small></div>
            <div class="node notify"><b>notification-service</b><small>email simulation</small></div>
            <div class="node analytics"><b>analytics-service</b><small>business events</small></div>
            <div class="node storage"><b>Postgres · Redis</b><small>orders, carts, analytics</small></div>
            <div class="node signoz hot"><b>SigNoz</b><small>logs · metrics · traces · alerts</small></div>
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
    const scenarios = Object.keys(scenarioDetails);
    const servicesEl = document.querySelector("#services");
    const scenariosEl = document.querySelector("#scenarios");
    const eventsEl = document.querySelector("#events");
    const okCountEl = document.querySelector("#ok-count");
    const lastCodeEl = document.querySelector("#last-code");

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
      addEvent(name, "Triggering scenario…");
      const res = await fetch("/api/scenarios", {
        method: "POST",
        headers: {"content-type": "application/json"},
        body: JSON.stringify({scenario: name, use_cart: false})
      });
      const data = await res.json();
      const order = data.response?.order_id || data.response?.detail?.reason || "see response";
      addEvent(name, `${data.expected || "Scenario completed."} Result: ${order}`, data.status_code || res.status);
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
