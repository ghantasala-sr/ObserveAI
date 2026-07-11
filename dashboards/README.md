# ObserveAI SigNoz Dashboard Pack

This folder contains dashboard plans and tested ClickHouse SQL queries for building ObserveAI dashboards in SigNoz.

SigNoz dashboards can be built from panels using Query Builder or SQL. These queries use the local SigNoz trace table:

```text
signoz_traces.distributed_signoz_index_v3
```

The queries are intentionally written with a rolling `now() - INTERVAL 15 MINUTE` window so they work immediately in local self-hosted SigNoz. After creating panels, use the SigNoz dashboard time picker for interactive exploration.

## Prerequisites

Keep the traffic generator running:

```bash
docker compose up -d --build
```

Open SigNoz:

```text
http://localhost:8080
```

Use time range:

```text
Last 15 minutes
```

## Dashboard 1: ObserveAI System Overview

Goal: understand global service health.

Recommended panels:

- `queries/system/service-span-volume.sql`
- `queries/system/service-latency-percentiles.sql`
- `queries/system/service-error-spans.sql`
- `queries/system/top-slow-operations.sql`

What to look for:

- `checkout-service` should have the most spans.
- `payment-service` should show visible latency from `payment_slow`.
- `checkout-service` and downstream services should show error spans from expected failure scenarios.

## Dashboard 2: Checkout Health

Goal: understand the main business workflow.

Recommended panels:

- `queries/checkout/checkout-latency-percentiles.sql`
- `queries/checkout/checkout-status-breakdown.sql`
- `queries/checkout/checkout-scenarios.sql`
- `queries/checkout/checkout-db-writes.sql`

What to look for:

- `p90` and `p99` should rise when `db_slow`, `payment_slow`, or `fraud_ai_slow` traffic is active.
- Error count should rise from `payment_fail`, `provider_timeout`, and `inventory_fail`.

## Dashboard 3: Payment Health

Goal: isolate payment bottlenecks.

Recommended panels:

- `queries/payment/payment-latency-percentiles.sql`
- `queries/payment/payment-errors.sql`
- `queries/payment/payment-provider-operation-latency.sql`

What to look for:

- `payment.provider_call` should clearly show latency spikes.
- Payment error spans should appear during `payment_fail` and `provider_timeout`.

## Dashboard 4: Database And Redis Health

Goal: see storage/cache behavior.

Recommended panels:

- `queries/storage/postgres-operation-latency.sql`
- `queries/storage/postgres-operation-volume.sql`
- `queries/storage/redis-operation-latency.sql`
- `queries/storage/redis-operation-volume.sql`

What to look for:

- `postgres slow_query` should have high p99 latency.
- `postgres insert_order` and `postgres upsert_fraud_result` should stay much faster.
- `redis get cart` and `redis set cart` should be frequent and fast.

## Dashboard 5: Fraud Pipeline

Goal: understand async fraud processing.

Recommended panels:

- `queries/fraud/fraud-service-latency.sql`
- `queries/fraud/fraud-decisions.sql`
- `queries/fraud/kafka-fraud-events.sql`

What to look for:

- `fraud.inference` should spike during `fraud_ai_slow`.
- `fraud.decision` should include `review` for high-value orders.
- Kafka publish spans should appear in checkout and fraud services.

## How To Create Panels In SigNoz

1. Open `http://localhost:8080`.
2. Go to Dashboards.
3. Create a new dashboard.
4. Add a panel.
5. Choose SQL/ClickHouse query mode if available.
6. Paste one query from this folder.
7. Pick the panel visualization:
   - Time series for latency/rate over time.
   - Bar chart/table for breakdowns.
   - Value/stat for totals.
8. Save the panel.

## Notes

- If a panel looks empty, run:

```bash
bash tests/big_smoke_test.sh
```

- Or keep continuous traffic enabled:

```bash
docker compose up -d --build
```

- If traffic is too noisy:

```bash
docker compose up -d --scale traffic-generator=0
```
