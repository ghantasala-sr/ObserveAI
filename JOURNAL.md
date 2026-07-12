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

Commit: `ab6c6d3 Enhance UI architecture map`

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

## 2026-07-11 - SigNoz Time-Series Dashboard Fix

Commit: pending until pushed

What changed:

- Updated time-series dashboard SQL files to use a SigNoz-friendly shape:
  - `ts` for the time bucket
  - a series label like `serviceName` or `operation`
  - `value` for the numeric value being plotted
- Fixed remaining queries that grouped by the raw `timestamp` instead of the time bucket alias.
- Added a known-good SigNoz smoke query to `dashboards/README.md`.

Why:

- SigNoz ClickHouse panels were showing `No Data` even though telemetry existed in ClickHouse.
- Direct validation showed fresh ObserveAI spans were present, so the problem was dashboard query formatting rather than ingestion.

Validation:

- Confirmed fresh spans in the SigNoz ClickHouse trace table for:
  - `checkout-service`
  - `inventory-service`
  - `payment-service`
  - `traffic-generator`
  - `ai-fraud-service`
  - `cart-service`
- Ran every SQL file in `dashboards/queries/*/*.sql` against the local SigNoz ClickHouse store.
- Verified all dashboard queries return rows.

Notes / follow-ups:

- In SigNoz, paste the known-good time-series smoke query, choose Time Series, then click **Stage & Run Query**.
- If the time-series panel still says `No Data`, run the table sanity query from `dashboards/README.md` to prove data exists.

## 2026-07-11 - SigNoz Alert Pack

Commit: pending until pushed

What changed:

- Added `alerts/README.md`.
- Added tested ClickHouse alert queries under `alerts/queries/`.
- Covered V1 operational alert signals:
  - checkout p99 latency
  - checkout error rate
  - payment provider error rate
  - payment provider p99 latency
  - PostgreSQL slow query p99 latency
  - Redis operation p99 latency
  - fraud AI p99 latency
  - ObserveAI telemetry silence
- Updated the main `README.md` with the new alert folder.

Why:

- Dashboards help us see system behavior, but alerts teach when a signal is dangerous enough to require action.
- This makes ObserveAI closer to real enterprise observability: detect, investigate, explain, then fix.

Validation:

- Ran every SQL file in `alerts/queries/*.sql` against the local SigNoz ClickHouse store.
- Verified all alert queries return a `value` column.
- Example live values during demo traffic:
  - checkout error rate around 43%
  - checkout p99 around 1.3s
  - fraud AI p99 around 1.5s
  - payment provider p99 around 1.2s
  - PostgreSQL slow query p99 around 1.1s
  - Redis p99 below 20ms
  - telemetry count well above the silence threshold

Notes / follow-ups:

- Next: manually create the first 2 or 3 SigNoz alert rules from the alert pack.
- Start with checkout p99 latency, checkout error rate, and payment provider error rate.

## 2026-07-11 - Alert Query Time-Series Fix

Commit: pending until pushed

What changed:

- Updated all alert ClickHouse queries to return:
  - `interval`
  - `value`
- Updated `alerts/README.md` to document this shape.

Why:

- Scalar alert queries returned a valid number in ClickHouse, but SigNoz alert rule charts need a time-series result to render and evaluate clearly.
- SigNoz alert docs describe alert ClickHouse queries as returning both `value` and an `interval` column for time-series evaluation.

Validation:

- Ran every SQL file in `alerts/queries/*.sql` against the local SigNoz ClickHouse store.
- Verified each query returns multiple recent time buckets with visible values.

Notes / follow-ups:

- Recreate or edit the checkout p99 alert with the updated query from `alerts/queries/checkout-p99-latency.sql`.

## 2026-07-11 - Kafka Lag And DLQ Scenarios

Commit: pending until pushed

What changed:

- Added two new demo scenarios:
  - `kafka_consumer_slow`
  - `poison_message`
- Updated `traffic-generator` and smoke tests to create both scenarios.
- Enhanced `ai-fraud-service` Kafka consumption:
  - estimates consumer lag on `fraud.inference` spans
  - simulates slow Kafka consumer processing
  - simulates poison-message retries
  - publishes failed poison messages to `fraud.check.dlq`
- Added dashboard queries:
  - `dashboards/queries/fraud/kafka-consumer-lag.sql`
  - `dashboards/queries/fraud/fraud-dlq-events.sql`
- Added alert queries:
  - `alerts/queries/kafka-fraud-consumer-lag.sql`
  - `alerts/queries/fraud-dlq-events.sql`
- Updated README, dashboard docs, alert docs, and dashboard plan.

Why:

- Enterprise systems often fail asynchronously, not only inside direct HTTP request/response paths.
- Kafka lag and dead-letter queues are core observability concepts for event-driven systems.
- This gives ObserveAI a realistic async failure story: checkout succeeds, but fraud processing falls behind or sends bad messages to DLQ.

Validation:

- Rebuilt and restarted changed services with Docker Compose.
- Verified traffic generator emits `kafka_consumer_slow` and `poison_message`.
- Verified fraud consumer logs show delayed processing and DLQ publishing.
- Ran `tests/smoke_test.sh` successfully.
- Ran new SigNoz ClickHouse queries and confirmed:
  - fraud consumer lag estimate reached `8`
  - fraud DLQ events reached `3`

Notes / follow-ups:

- Add the new panels to the `ObserveAI Fraud Pipeline` dashboard.
- Optional next step: add a dedicated notification-service consumer and analytics-service consumer.

## 2026-07-12 - Downstream Notification And Analytics Consumers

Commit: pending until pushed

What changed:

- Added `notification-service`.
- Added `analytics-service`.
- Added Postgres tables:
  - `notifications`
  - `analytics_events`
- Updated `fraud.check.completed` events to carry the original scenario.
- Added new scenarios:
  - `notification_slow`
  - `notification_fail`
  - `analytics_slow`
- Updated traffic generator and smoke tests to produce the new scenarios.
- Added a `latest` offset option for new downstream Kafka consumers so demo consumers focus on fresh traffic instead of replaying old backlog.
- Added dashboard queries for:
  - notification latency
  - notification sent/failed status
  - analytics processing latency
  - analytics event volume
- Added alert queries for:
  - notification error rate
  - notification p99 latency
  - analytics p99 latency
  - analytics DLQ processing
- Updated README, dashboard docs, alert docs, Docker Compose, and dashboard plan.

Why:

- Real enterprise event pipelines fan out to multiple downstream consumers after a business event.
- This extends ObserveAI beyond checkout/fraud into customer notifications and business analytics.
- It teaches that a checkout can succeed while downstream async systems become slow, fail, or process DLQ events.

Validation:

- Rebuilt and restarted the stack with Docker Compose.
- Confirmed `notification-service` and `analytics-service` are running.
- Ran `tests/smoke_test.sh` successfully.
- Verified logs show:
  - `notification_slow`
  - `notification_fail`
  - `analytics_slow`
  - analytics DLQ processing
- Ran every SQL file in `dashboards/queries` and `alerts/queries` against SigNoz ClickHouse.
- Verified all dashboard and alert queries return rows.

Notes / follow-ups:

- Add the new `ObserveAI Downstream Consumers` dashboard in SigNoz.
- Consider adding a rules-based recommendation consumer next.

## 2026-07-12 - ObserveAI Web UI And Architecture Map

Commit: `e3a3508 Add ObserveAI web UI and architecture map`

What changed:

- Added `ui-service`.
- Exposed the UI at `http://localhost:18082`.
- Added a polished local control room interface with:
  - service health checks
  - scenario launcher
  - architecture map
  - recent event trail
  - direct SigNoz link
- Added UI API endpoints:
  - `GET /api/services`
  - `POST /api/cart/seed`
  - `POST /api/scenarios`
- Updated Docker Compose to run the UI service.
- Updated smoke test to check `ui-service` health.
- Updated README and `.env.example`.

Why:

- ObserveAI needed a human-friendly demo surface instead of only curl commands.
- The architecture map makes the system easier to explain: UI, checkout, sync dependencies, Kafka, fraud, notification, analytics, storage, and SigNoz.
- Triggering scenarios from the browser makes it faster to create fresh traces, dashboard changes, and alert conditions.

Validation:

- Built and started `ui-service` with Docker Compose.
- Confirmed `http://localhost:18082/health` returns healthy.
- Confirmed the HTML page loads.
- Confirmed `GET /api/services` returns healthy downstream service statuses.
- Triggered a `normal` scenario through the UI API successfully.
- Ran `tests/smoke_test.sh` successfully.
- Verified `ui-service` spans are landing in SigNoz ClickHouse.
- Ran `python3 -m compileall services shared` successfully.

Notes / follow-ups:

- Open `http://localhost:18082` and use it as the main demo surface.
- Next useful improvement: add a small live “last trace/order id” panel or dashboard deep links.

## 2026-07-12 - Pictorial Kafka And SigNoz Architecture UI

Commit: pending until pushed

What changed:

- Reworked the UI architecture section into a more pictorial system map.
- Added explicit visual areas for:
  - browser and `ui-service`
  - `checkout-service`
  - synchronous dependencies: cart, inventory, payment
  - state layer: PostgreSQL and Redis
  - Redpanda / Kafka-compatible event bus
  - Kafka topics: `fraud.check.requested`, `fraud.check.completed`, `fraud.check.dlq`
  - async consumers: AI fraud, notification, analytics
  - OpenTelemetry Collector and SigNoz
  - SigNoz traces, logs, metrics, dashboards, and alerts
- Added a legend for HTTP sync calls, Kafka events, and OTLP telemetry.
- Added scenario-based highlighting so clicking a scenario lights up the affected parts of the architecture.
- Updated README to describe the richer UI and note `http://127.0.0.1:18082` as the safer local URL if `localhost` resets.

Why:

- The previous map was useful but still felt like a simple box diagram.
- We wanted the UI to teach the full observability story visually: request path, async event path, storage, telemetry export, dashboards, and alerts.
- Scenario highlighting makes the UI more useful for demos because it connects “what I triggered” to “where I should look in SigNoz.”

Validation:

- Ran `python3 -m compileall services/ui/main.py`.
- Rebuilt and restarted `ui-service` with Docker Compose.
- Confirmed `http://127.0.0.1:18082/health` returns healthy.
- Confirmed the page contains the new Redpanda/Kafka, OpenTelemetry Collector, dashboard, alert, and DLQ architecture content.
- Triggered `payment_slow` through the UI API successfully.
- Ran `tests/smoke_test.sh` successfully.
- Verified fresh `ui-service`, `checkout-service`, and `payment-service` spans in SigNoz ClickHouse.

Notes / follow-ups:

- If `localhost:18082` resets on macOS, use `127.0.0.1:18082`.
- Next useful UI improvement: show the last order id and trace helper directly inside the page.
- Another good next UI improvement: add links/buttons that open the relevant SigNoz dashboard or alert docs.

## 2026-07-12 - Scenario Flow Simulator In UI

Commit: `3712eaf Animate scenario flows in UI`

What changed:

- Added animated scenario flows to the architecture map.
- When a user triggers a scenario, the UI now animates:
  - HTTP request movement through browser, UI, checkout, and sync dependencies
  - Kafka / Redpanda event movement through topics and async consumers
  - OTLP telemetry movement into the OpenTelemetry Collector and SigNoz
- Added a flow readout that explains what the selected scenario is doing.
- Added a SigNoz capture panel that explains what observability catches for that scenario.
- Added different visual packet styles for:
  - HTTP traffic
  - Kafka events
  - telemetry
  - error/failure paths

Why:

- The user wanted to simulate not just the static architecture, but how a scenario moves through the system and how observability catches it.
- This makes the UI a stronger learning surface: you can click `payment_slow`, `kafka_consumer_slow`, `poison_message`, etc., and visually connect the runtime path to traces, metrics, logs, dashboards, and alerts.

Validation:

- Ran `python3 -m compileall services/ui/main.py`.
- Parsed the inline browser JavaScript with `node --check`.
- Rebuilt and restarted `ui-service`.
- Confirmed `http://127.0.0.1:18082/health` returns healthy.
- Confirmed the page contains the new flow simulator and SigNoz capture content.
- Triggered `kafka_consumer_slow` through the UI API successfully.

Notes / follow-ups:

- Next useful UI improvement: after a scenario completes, show the returned `order_id` in a dedicated trace helper panel.
- After that, add direct links or instructions for the matching SigNoz dashboard and alert query.

## 2026-07-12 - Trace Helper Investigation Panel

Commit: `a8d4872 Add UI trace helper`

What changed:

- Added a Trace Helper panel to the UI.
- After a scenario runs, the panel now shows:
  - scenario name
  - returned `order_id`
  - response status
  - likely bottleneck or failure focus
  - where to look in SigNoz
  - dashboard hint
  - alert candidate
  - copyable ClickHouse query scoped to the scenario/order id
- Added scenario-specific investigation guides for payment, inventory, Kafka lag, poison/DLQ, notification, analytics, AI fraud, and database slow paths.

Why:

- The animation shows how traffic and telemetry move through the architecture.
- The Trace Helper tells the user how to investigate the exact run in SigNoz.
- This bridges the learning gap between “I triggered a failure” and “I know what evidence to search for.”

Validation:

- Ran `python3 -m compileall services/ui/main.py`.
- Parsed the inline browser JavaScript with `node --check`.
- Rebuilt and restarted `ui-service`.
- Confirmed `http://127.0.0.1:18082/health` returns healthy.
- Confirmed the UI contains the Trace Helper section.
- Triggered `payment_slow` through the UI API successfully.
- Ran the generated helper-style ClickHouse query against SigNoz and confirmed it returns the exact slow payment trace rows.

Notes / follow-ups:

- Next useful UI improvement: make the helper produce direct links to specific saved dashboard docs or setup instructions.
- Later, this helper can become the prompt/context payload for the SigNoz MCP SRE Sidekick.

## 2026-07-12 - SigNoz MCP Learning Integration

Commit: pending until pushed

What changed:

- Added MCP learning documentation under `docs/mcp/`.
- Added a Foundry casting example with MCP enabled:
  - `docs/mcp/casting-with-mcp.example.yaml`
- Added a safe Codex HTTP MCP config example:
  - `docs/mcp/codex-http.example.toml`
- Added `scripts/check_mcp.sh` to verify the local SigNoz MCP health endpoint.
- Updated README with the MCP practice workflow.

Why:

- We want to understand MCP before the hackathon without using ObserveAI as the hackathon project.
- MCP is important because SigNoz recommends it for AI assistant workflows over traces, logs, metrics, dashboards, and alerts.
- This gives us a safe practice path: ObserveAI generates telemetry, SigNoz stores it, MCP lets an AI assistant investigate it.

Validation:

- Verified from official SigNoz docs that Foundry is the supported self-host Docker install path and that MCP is enabled through an `mcp.spec.enabled: true` block in `casting.yaml`.
- Verified from official SigNoz docs that local self-hosted MCP exposes HTTP mode at `http://localhost:8000/mcp` and health at `/livez`.
- Ran `bash -n scripts/check_mcp.sh`.
- Ran `bash scripts/check_mcp.sh`; it correctly reported that local MCP is not enabled/running yet on port `8000`.
- Added docs and scripts without committing secrets.

Notes / follow-ups:

- We still need to enable MCP in the actual local SigNoz Foundry deployment.
- We still need to create a SigNoz service-account API key locally.
- Once connected, try prompts like “Investigate the latest payment_slow scenario” and “Find Kafka lag or DLQ evidence.”

## Next Best Steps

Recommended next steps:

1. Enable SigNoz MCP in the local Foundry `casting.yaml` and verify `http://localhost:8000/livez`.
2. Connect Codex/Claude/Cursor to `http://localhost:8000/mcp`.
3. Use MCP to investigate ObserveAI scenarios in natural language.
4. Add dashboard deep links or alert setup links to the UI.
5. Add the `ObserveAI Downstream Consumers` dashboard in SigNoz.
6. Create notification and analytics alerts from `alerts/README.md`.
7. Add a rules-based recommendation service.
8. Later, build the separate hackathon AI Agent Observability project.

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
