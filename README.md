# ObserveAI

ObserveAI is a V1 observability lab for learning how production systems behave across synchronous services, Kafka-style async flows, basic AI services, OpenTelemetry, and SigNoz.

This version is intentionally not an AI copilot yet. First we build the system that an AI copilot would later observe.

## What V1 Includes

- FastAPI checkout, payment, inventory, and rules-based AI fraud services.
- Redpanda as a Kafka-compatible broker.
- PostgreSQL for ObserveAI orders and fraud results.
- Redis for cart/cache state.
- Continuous traffic generator for live SigNoz metrics.
- Local web UI for scenario triggering, service health, and a pictorial architecture map.
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
ui-service
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
  |----> notification-service -> PostgreSQL notifications
  |
  v
analytics-service -> PostgreSQL analytics_events

All services -> OpenTelemetry Collector -> SigNoz
```

The `traffic-generator` service continuously calls checkout and cart flows so SigNoz keeps receiving live data.

## Prerequisites

- Docker Desktop with at least 4 GB memory available.
- SigNoz running locally with OTLP/gRPC available on `localhost:4317`.

Current SigNoz self-hosted Docker installs use Foundry. Start SigNoz separately from this app, then run ObserveAI. ObserveAI keeps its collector internal, joins the `signoz-network` Docker network, and exposes checkout on `18080`, so SigNoz can keep its normal OTLP and UI ports. See the official SigNoz Docker guide: https://signoz.io/docs/install/docker/

## Run

```bash
cp .env.example .env
docker compose up --build
```

To run without continuous generated traffic:

```bash
docker compose up --build --scale traffic-generator=0
```

The checkout API is exposed at:

```text
http://localhost:18080
```

The cart API is exposed at:

```text
http://localhost:18081
```

The ObserveAI web UI is exposed at:

```text
http://localhost:18082
```

If `localhost` gives a connection reset on your machine, use the explicit loopback address:

```text
http://127.0.0.1:18082
```

Use it to:

- check service health
- trigger demo scenarios
- inspect the pictorial architecture map across HTTP, Kafka/Redpanda, async consumers, storage, OpenTelemetry, and SigNoz
- watch each scenario animate through the architecture as HTTP packets, Kafka events, and OTLP telemetry pulses
- see how each scenario maps to traces, metrics, dashboards, and alerts
- use the Trace Helper to inspect the latest scenario, order id, likely bottleneck, SigNoz checklist, dashboard hint, alert candidate, and copyable ClickHouse query
- jump into SigNoz

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
| `kafka_consumer_slow` | Checkout succeeds, fraud Kafka consumer intentionally falls behind. |
| `poison_message` | Checkout succeeds, fraud consumer retries and sends message to DLQ. |
| `notification_slow` | Checkout succeeds, notification consumer is intentionally slow. |
| `notification_fail` | Checkout succeeds, notification consumer records a provider failure. |
| `analytics_slow` | Checkout succeeds, analytics consumer is intentionally slow. |
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

## Continuous Traffic

By default, Docker Compose starts `traffic-generator`.

It continuously creates:

- normal checkouts
- slow payment requests
- payment failures
- provider timeouts
- inventory failures
- slow database requests
- slow fraud-service requests
- slow/failing notification requests
- slow analytics consumer requests
- cart-backed checkouts

Tune the volume in `docker-compose.yml` or `.env`:

```text
TRAFFIC_INTERVAL_SECONDS=2.0
TRAFFIC_BURST_SIZE=3
```

## What To Look For In SigNoz

- Services: `checkout-service`, `payment-service`, `inventory-service`, `ai-fraud-service`, `cart-service`, `traffic-generator`.
- UI service: `ui-service`.
- Additional services: `cart-service`, PostgreSQL spans, Redis spans.
- A checkout trace with HTTP spans for inventory and payment.
- Kafka producer span from checkout to `fraud.check.requested`.
- Kafka consumer span in `ai-fraud-service`.
- Kafka consumer lag estimate on `fraud.inference` spans.
- DLQ publish spans for `fraud.check.dlq` during poison-message scenarios.
- Notification consumer spans after fraud checks complete.
- Analytics consumer spans for completed fraud and DLQ events.
- PostgreSQL order writes and fraud-result writes.
- PostgreSQL notification and analytics writes.
- Redis cart cache hit/miss spans.
- Logs that include `trace_id`, `span_id`, `order_id`, and safe scenario metadata.
- Metrics such as `checkout_requests_total`, `payment_failures_total`, and `fraud_high_risk_orders_total`.

## Dashboards

Dashboard plans and tested SQL panel queries are in:

```text
dashboards/
```

Start with:

```text
dashboards/README.md
```

Included dashboard groups:

- System Overview
- Checkout Health
- Payment Health
- Database and Redis Health
- Fraud Pipeline
- Downstream Consumers

## Alerts

Alert plans and tested ClickHouse alert queries are in:

```text
alerts/
```

Start with:

```text
alerts/README.md
```

Included V1 alert signals:

- Checkout p99 latency
- Checkout error rate
- Payment provider error rate
- Payment provider p99 latency
- PostgreSQL slow query p99 latency
- Redis/cache p99 latency
- Fraud AI p99 latency
- Fraud Kafka consumer lag
- Fraud DLQ events
- Notification error rate and p99 latency
- Analytics p99 latency and DLQ processing
- ObserveAI telemetry silence

## SigNoz MCP Practice

MCP learning notes and safe local config examples are in:

```text
docs/mcp/
```

Start with:

```text
docs/mcp/README.md
```

Quick health check after enabling SigNoz MCP through Foundry:

```bash
bash scripts/check_mcp.sh
```

This is a practice integration for learning how AI assistants can query SigNoz telemetry. Do not commit API keys or local MCP secrets.

## V1 Boundary

ObserveAI V1 uses deterministic rules for fraud scoring. It does not require Claude, ChatGPT, OpenAI, or any paid LLM API.

Later versions can add:

- AI recommendation service.
- Notification and analytics consumers.
- Deeper SigNoz MCP workflows.
- SRE Sidekick AI copilot on top of the telemetry.
