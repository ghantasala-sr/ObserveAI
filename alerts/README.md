# ObserveAI SigNoz Alert Pack

This folder contains copy-paste alert queries for SigNoz.

The goal is to turn the dashboard signals into operational alerts:

- checkout latency
- checkout failures
- payment provider failures
- PostgreSQL slow queries
- Redis/cache latency
- AI fraud inference latency
- telemetry silence

All queries use the local SigNoz trace table:

```text
signoz_traces.distributed_signoz_index_v3
```

## How To Create Alerts In SigNoz

1. Open SigNoz at `http://localhost:8080`.
2. Go to Alerts.
3. Create a new alert rule.
4. Choose ClickHouse query mode.
5. Paste one query from `alerts/queries/`.
6. Use the returned `value` column as the alert signal.
7. Set the threshold listed below.
8. Evaluate every 1 minute.
9. Require the condition for 3 to 5 minutes before firing.

Important:

- SigNoz alert ClickHouse queries should return:
  - `interval`: the time bucket
  - `value`: the numeric value to evaluate
- If the chart is blank, first make sure your query returns both `interval` and `value`.

## Recommended V1 Alerts

| Alert | Query file | Threshold | Severity | Why it matters |
| --- | --- | --- | --- | --- |
| Checkout p99 latency high | `queries/checkout-p99-latency.sql` | `value > 1000` ms | Critical | User-facing checkout is slow. |
| Checkout error rate high | `queries/checkout-error-rate.sql` | `value > 20` percent | Critical | Checkout is failing too often. |
| Payment provider error rate high | `queries/payment-provider-error-rate.sql` | `value > 20` percent | Critical | Payment dependency is unhealthy. |
| Payment provider p99 latency high | `queries/payment-provider-p99-latency.sql` | `value > 800` ms | Warning | Payment is becoming a bottleneck. |
| PostgreSQL slow query p99 high | `queries/postgres-slow-query-p99.sql` | `value > 500` ms | Warning | Database path is slow. |
| Redis operation p99 high | `queries/redis-p99-latency.sql` | `value > 50` ms | Warning | Cart/cache path is slow. |
| Fraud AI p99 latency high | `queries/fraud-ai-p99-latency.sql` | `value > 500` ms | Warning | AI inference is slowing the fraud pipeline. |
| Fraud Kafka consumer lag high | `queries/kafka-fraud-consumer-lag.sql` | `value > 20` messages | Warning | Fraud consumer is falling behind. |
| Fraud DLQ events detected | `queries/fraud-dlq-events.sql` | `value > 0` events | Critical | Fraud messages are failing after retries. |
| Notification error rate high | `queries/notification-error-rate.sql` | `value > 10` percent | Warning | Customer notifications are failing. |
| Notification p99 latency high | `queries/notification-p99-latency.sql` | `value > 1000` ms | Warning | Notification provider/path is slow. |
| Analytics p99 latency high | `queries/analytics-p99-latency.sql` | `value > 1000` ms | Warning | Business analytics consumer is slow. |
| Analytics DLQ events detected | `queries/analytics-dlq-events.sql` | `value > 0` events | Warning | Analytics observed fraud DLQ events. |
| ObserveAI telemetry silent | `queries/observeai-telemetry-silence.sql` | `value < 50` spans | Critical | Services or traffic generator may be down. |

## Suggested Alert Messages

### Checkout p99 latency high

```text
ObserveAI checkout p99 latency is above 1 second.
Check the Checkout Health dashboard, then inspect slow traces for checkout.workflow.
Likely demo causes: payment_slow, fraud_ai_slow, or db_slow.
```

### Checkout error rate high

```text
ObserveAI checkout error rate is high.
Check error spans by scenario and inspect payment/inventory traces.
Likely demo causes: payment_fail, provider_timeout, or inventory_fail.
```

### Payment provider issue

```text
ObserveAI payment provider is unhealthy.
Check payment.provider_call spans and payment-service logs.
Likely demo causes: payment_slow, payment_fail, or provider_timeout.
```

### Fraud AI latency high

```text
ObserveAI fraud AI inference latency is high.
Check fraud.inference spans and the Fraud Pipeline dashboard.
Likely demo cause: fraud_ai_slow.
```

### Fraud Kafka consumer lag high

```text
ObserveAI fraud consumer lag is increasing.
Check the Fraud Pipeline dashboard and fraud.inference spans.
Likely demo cause: kafka_consumer_slow.
```

### Fraud DLQ event detected

```text
ObserveAI fraud message was sent to the DLQ.
Check kafka publish fraud.check.dlq spans and poison retry spans.
Likely demo cause: poison_message.
```

### Notification error rate high

```text
ObserveAI notification-service is failing notifications.
Check notification.send spans and notification-service logs.
Likely demo cause: notification_fail.
```

### Analytics p99 latency high

```text
ObserveAI analytics-service event processing is slow.
Check analytics.process_fraud_completed spans.
Likely demo cause: analytics_slow.
```

## How To Test Alerts

Keep continuous traffic running:

```bash
docker compose up -d --build
```

The traffic generator intentionally creates latency and error scenarios, so several warning-style alerts may cross their thresholds during normal demo traffic.

To create a sharper spike, run:

```bash
bash tests/big_smoke_test.sh
```

Then watch:

- Dashboards for trend changes
- Alerts for firing conditions
- Traces for root cause

## Alert Design Notes

- V1 alerts intentionally use simple thresholds.
- The queries return a time series with `interval` and `value` because SigNoz alert rules evaluate time-series results.
- In real production, thresholds should be tuned using baseline traffic.
- Prefer user-impact alerts first: checkout latency and checkout failures.
- Infrastructure alerts are useful, but they should not page people unless they affect user-facing workflows.
