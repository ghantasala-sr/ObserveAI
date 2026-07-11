# ObserveAI

ObserveAI is a V1 observability lab for learning how production systems behave across synchronous services, Kafka-style async flows, basic AI services, OpenTelemetry, and SigNoz.

This version is intentionally not an AI copilot yet. First we build the system that an AI copilot would later observe.

## What V1 Includes

- FastAPI checkout, payment, inventory, and rules-based AI fraud services.
- Redpanda as a Kafka-compatible broker.
- PostgreSQL for ObserveAI orders and fraud results.
- Redis for cart/cache state.
- OpenTelemetry traces, metrics, and logs.
- Trace context propagation across HTTP and Kafka headers.
- Privacy-safe structured JSON logs with trace and span ids.
- Failure scenarios for payment, inventory, and fraud latency.
- A local OpenTelemetry Collector that forwards telemetry to SigNoz.

## Architecture

```text
Client
  |
  v
checkout-service
  |----> cart-service -> Redis
  |----> inventory-service
  |----> payment-service
  |----> PostgreSQL orders
  |
  v
Redpanda topic: fraud.check.requested
  |
  v
ai-fraud-service
  |
  v
Redpanda topic: fraud.check.completed

All services -> OpenTelemetry Collector -> SigNoz
```

## Prerequisites

- Docker Desktop with at least 4 GB memory available.
- SigNoz running locally with OTLP/gRPC available on `localhost:4317`.

Current SigNoz self-hosted Docker installs use Foundry. Start SigNoz separately from this app, then run ObserveAI. ObserveAI keeps its collector internal, joins the `signoz-network` Docker network, and exposes checkout on `18080`, so SigNoz can keep its normal OTLP and UI ports. See the official SigNoz Docker guide: https://signoz.io/docs/install/docker/

## Run

```bash
cp .env.example .env
docker compose up --build
```

The checkout API is exposed at:

```text
http://localhost:18080
```

The cart API is exposed at:

```text
http://localhost:18081
```

## Try A Normal Checkout

```bash
curl -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_123",
    "amount": 799.0,
    "items": [{"product_id": "laptop", "quantity": 1}],
    "scenario": "normal",
    "idempotency_key": "demo-001"
  }'
```

## Failure Scenarios

Use the `scenario` field to create useful observability signals:

| Scenario | Expected Behavior |
| --- | --- |
| `normal` | Checkout succeeds, fraud event is queued. |
| `payment_slow` | Payment span becomes slow, checkout latency rises. |
| `payment_fail` | Payment returns 502 and checkout fails. |
| `provider_timeout` | Simulated provider timeout-style failure. |
| `inventory_fail` | Inventory returns 409 out-of-stock. |
| `fraud_ai_slow` | Checkout succeeds, async fraud consumer is slow. |
| `db_slow` | Checkout succeeds with an intentionally slow DB step. |

## Smoke Test

```bash
bash tests/smoke_test.sh
```

For a bigger telemetry run with latency spikes, expected failures, Kafka activity, and AI fraud-service spans:

```bash
bash tests/big_smoke_test.sh
```

You can increase or decrease the load:

```bash
TOTAL_REQUESTS=150 bash tests/big_smoke_test.sh
```

## What To Look For In SigNoz

- Services: `checkout-service`, `payment-service`, `inventory-service`, `ai-fraud-service`.
- Additional services: `cart-service`, PostgreSQL spans, Redis spans.
- A checkout trace with HTTP spans for inventory and payment.
- Kafka producer span from checkout to `fraud.check.requested`.
- Kafka consumer span in `ai-fraud-service`.
- PostgreSQL order writes and fraud-result writes.
- Redis cart cache hit/miss spans.
- Logs that include `trace_id`, `span_id`, `order_id`, and safe scenario metadata.
- Metrics such as `checkout_requests_total`, `payment_failures_total`, and `fraud_high_risk_orders_total`.

## V1 Boundary

ObserveAI V1 uses deterministic rules for fraud scoring. It does not require Claude, ChatGPT, OpenAI, or any paid LLM API.

Later versions can add:

- AI recommendation service.
- Notification and analytics consumers.
- Dashboard and alert definitions.
- SigNoz MCP integration.
- SRE Sidekick AI copilot on top of the telemetry.
