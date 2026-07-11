# ObserveAI Journal

This journal records how ObserveAI is evolving: what we built, why we made each decision, what worked, what broke, and what we should do next. Keep this updated whenever the project changes meaningfully.

## 2026-07-11 - Project Origin And Direction

We started with a broad goal: understand observability deeply before building an AI SRE copilot. The first idea was not to jump directly into MCP or a chatbot. The better learning path was to build a small production-style system that generates real telemetry.

The project name was finalized as `ObserveAI`.

The initial product direction:

- Build a microservices observability lab.
- Use SigNoz as the observability platform.
- Use OpenTelemetry for traces, metrics, and logs.
- Use Kafka-compatible event streaming through Redpanda.
- Add basic AI services, but keep V1 rules-based instead of using paid LLM APIs.
- Later, build an AI SRE Sidekick on top of this system.

Key decision:

ObserveAI V1 should be an observable system first. The AI copilot comes later, after we understand logs, metrics, traces, dashboards, alerts, Kafka, DB, cache, and service dependency behavior.

## 2026-07-11 - Initial ObserveAI App

Commit: `ef1dd29 Initial ObserveAI observability lab`

We created the first runnable ObserveAI application.

What was added:

- `checkout-service`
- `payment-service`
- `inventory-service`
- `ai-fraud-service`
- Redpanda as Kafka-compatible event streaming
- OpenTelemetry Collector
- Structured JSON logging
- Trace context propagation across HTTP and Kafka
- Basic smoke test
- Root README

V1 checkout flow:

```text
Client
  -> checkout-service
  -> inventory-service
  -> payment-service
  -> Redpanda topic: fraud.check.requested
  -> ai-fraud-service
  -> Redpanda topic: fraud.check.completed
```

The AI fraud service was intentionally simple and rules-based:

- High order value increases risk.
- High item count increases risk.
- High value plus multiple items leads to review.

This avoided needing OpenAI, Claude, or any other LLM API for V1.

## 2026-07-11 - SigNoz Port Conflict Fix

Commit: `91cd1d8 Avoid SigNoz port conflicts`

Problem:

ObserveAI originally exposed its local OpenTelemetry Collector on host ports `4317` and `4318`. SigNoz also needs those ports for OTLP ingestion. That caused a conflict with a local SigNoz install.

Fix:

- Removed host port exposure from ObserveAI's collector.
- Moved ObserveAI checkout API from `8080` to `18080`.
- Left SigNoz free to use:
  - `8080` for UI
  - `4317` for OTLP/gRPC
  - `4318` for OTLP/HTTP

Result:

ObserveAI and SigNoz can now run side by side locally.

## 2026-07-11 - Connected ObserveAI To SigNoz Correctly

Commit: `15a9d5a Route telemetry through SigNoz network`

Problem:

ObserveAI generated telemetry, but it was not appearing in SigNoz. The ObserveAI collector was exporting to `host.docker.internal:4317`, which produced errors like:

```text
connection refused
error reading server preface: EOF
```

Investigation:

SigNoz Foundry was running its containers on a Docker network named `signoz-network`. Its OTLP collector was reachable inside that network as `signoz-ingester:4317`.

Fix:

- Attached ObserveAI's OpenTelemetry Collector to `signoz-network`.
- Changed the exporter endpoint from:

```text
host.docker.internal:4317
```

to:

```text
signoz-ingester:4317
```

Result:

Telemetry started landing in SigNoz. We confirmed service spans for:

- `checkout-service`
- `payment-service`
- `inventory-service`
- `ai-fraud-service`

## 2026-07-11 - Telemetry-Heavy Smoke Test

Commit: `937dbeb Add telemetry-heavy smoke test`

We added `tests/big_smoke_test.sh`.

Purpose:

Generate enough traffic to make SigNoz interesting. The original smoke test only sent a couple of happy-path requests, which was not enough for meaningful observability exploration.

The big smoke test creates:

- Normal checkouts
- Slow payment scenarios
- Payment failures
- Provider timeout failures
- Inventory failures
- Slow fraud AI scenarios
- Kafka producer and consumer spans
- Error logs
- Latency spikes

Verified result from one run:

```text
80 total checkout requests
56 successful checkouts
24 expected failures
0 unexpected results
```

SigNoz then showed hundreds of spans across the services.

## 2026-07-11 - V2: PostgreSQL And Redis Observability

Commit: `40b82d6 Add Postgres and Redis observability paths`

This was the best next step after V1. We needed more realistic enterprise signals: database writes, cache hits/misses, and a cart service.

What was added:

- PostgreSQL for ObserveAI application data
- Redis for cart/cache state
- `cart-service`
- PostgreSQL order persistence
- PostgreSQL fraud-result persistence
- Redis cart storage
- Cart-backed checkout flow
- `db_slow` scenario with real `SELECT pg_sleep(1)`
- Big smoke test updates for DB and cache traffic

New services and ports:

```text
checkout-service docs: http://localhost:18080/docs
cart-service docs:     http://localhost:18081/docs
SigNoz UI:             http://localhost:8080
Postgres host port:    localhost:15432
Redis host port:       localhost:16379
```

New V2 flow:

```text
Client
  -> cart-service -> Redis
  -> checkout-service
  -> inventory-service
  -> payment-service
  -> PostgreSQL orders
  -> Redpanda fraud.check.requested
  -> ai-fraud-service
  -> PostgreSQL fraud_results
  -> Redpanda fraud.check.completed
```

Verified persistence:

```text
Postgres orders:        51
Postgres fraud_results: 51
```

Verified SigNoz spans:

```text
checkout-service      1212 spans
inventory-service      725 spans
payment-service        665 spans
ai-fraud-service       269 spans
cart-service           147 spans
```

Verified DB/cache spans:

```text
postgres upsert_fraud_result
postgres insert_order
postgres slow_query
redis get cart
redis set cart
redis ping
```

## Current State

ObserveAI is now a realistic local observability lab with:

- Synchronous microservice calls
- Async Kafka-style event flow
- PostgreSQL persistence
- Redis cache/cart behavior
- Rules-based AI fraud scoring
- Failure scenarios
- Slow latency scenarios
- Logs, metrics, and traces flowing to SigNoz

## 2026-07-11 - Continuous Traffic Generator

Commit: pending until pushed

We added a `traffic-generator` service so SigNoz has continuous data without manually running smoke tests.

What changed:

- Added `services/traffic`.
- Added a Docker Compose `traffic-generator` service.
- Added tunable traffic controls:
  - `TRAFFIC_INTERVAL_SECONDS`
  - `TRAFFIC_BURST_SIZE`
- The generator creates a steady mix of:
  - normal checkouts
  - slow payment requests
  - payment failures
  - provider timeouts
  - inventory failures
  - slow database requests
  - slow fraud-service requests
  - cart-backed checkouts

Why:

Observability needs live signals. Without continuous traffic, SigNoz becomes quiet after smoke tests finish. This generator keeps request rate, latency, errors, DB spans, Redis spans, Kafka spans, logs, and service metrics active.

Validation:

- `python3 -m compileall shared services` passed.
- `docker compose config --quiet` passed.
- `docker compose up -d --build` started `traffic-generator`.
- `docker compose ps` showed `observeai-traffic-generator-1` running.
- Traffic generator logs showed continuous mixed scenarios.
- SigNoz trace store showed fresh spans in the last 5 minutes:

```text
checkout-service      134 spans
inventory-service     105 spans
payment-service        90 spans
traffic-generator      38 spans
ai-fraud-service       36 spans
cart-service           22 spans
```

Notes / follow-ups:

- Next: build SigNoz dashboards on top of this steady traffic.

## 2026-07-11 - Dashboard Query Pack

Commit: pending until pushed

We added a first ObserveAI dashboard pack under `dashboards/`.

What changed:

- Added `dashboards/README.md`.
- Added `dashboards/dashboard-plan.json`.
- Added tested SQL panel queries for:
  - System Overview
  - Checkout Health
  - Payment Health
  - Database and Redis Health
  - Fraud Pipeline

Why:

Continuous traffic gives us live telemetry, but dashboards make the system easier to read. The goal is to quickly see service rate, latency, error spans, slow operations, PostgreSQL behavior, Redis behavior, and async fraud pipeline behavior.

Validation:

- Ran every SQL file in `dashboards/queries/*/*.sql` against the local SigNoz ClickHouse store.
- Verified results for:
  - service span volume
  - p50/p90/p99 latency
  - error span percentage
  - checkout scenarios
  - payment errors
  - PostgreSQL operation latency
  - Redis operation latency
  - fraud decisions
  - Kafka fraud events

Notes / follow-ups:

- Next: create alert definitions for the same signals.

## Next Best Steps

Recommended next steps:

1. Add SigNoz alerts.
2. Add Kafka consumer lag and dead-letter queue scenarios.
3. Add `notification-service`.
4. Add `analytics-service`.
5. Add rules-based recommendation service.
6. Add a small frontend UI for triggering scenarios.
7. Later, add SigNoz MCP and build the SRE Sidekick copilot.

## Journal Template For Future Work

Use this template whenever we make a meaningful change:

```markdown
## YYYY-MM-DD - Short Title

Commit: `<commit hash if available>`

What changed:

- ...

Why:

- ...

Validation:

- ...

Notes / follow-ups:

- ...
```
