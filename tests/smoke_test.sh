#!/usr/bin/env bash
set -euo pipefail

for _ in {1..30}; do
  if curl -fsS http://localhost:18080/health >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://localhost:18080/health
curl -fsS http://localhost:18081/health

curl -fsS -X POST http://localhost:18081/cart \
  -H "content-type: application/json" \
  -d '{
    "user_id": "cart_user_smoke",
    "items": [{"product_id": "keyboard", "quantity": 1}]
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_123",
    "amount": 799.0,
    "items": [{"product_id": "laptop", "quantity": 1}],
    "scenario": "normal",
    "idempotency_key": "smoke-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_456",
    "amount": 1200.0,
    "items": [{"product_id": "camera", "quantity": 6}],
    "scenario": "fraud_ai_slow",
    "idempotency_key": "smoke-002"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "cart_user_smoke",
    "amount": 129.0,
    "scenario": "normal",
    "idempotency_key": "smoke-cart-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_kafka_slow",
    "amount": 999.0,
    "items": [{"product_id": "monitor", "quantity": 4}],
    "scenario": "kafka_consumer_slow",
    "idempotency_key": "smoke-kafka-slow-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_poison",
    "amount": 459.0,
    "items": [{"product_id": "speaker", "quantity": 2}],
    "scenario": "poison_message",
    "idempotency_key": "smoke-poison-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_notification_slow",
    "amount": 219.0,
    "items": [{"product_id": "webcam", "quantity": 1}],
    "scenario": "notification_slow",
    "idempotency_key": "smoke-notification-slow-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_notification_fail",
    "amount": 189.0,
    "items": [{"product_id": "dock", "quantity": 1}],
    "scenario": "notification_fail",
    "idempotency_key": "smoke-notification-fail-001"
  }'

curl -fsS -X POST http://localhost:18080/checkout \
  -H "content-type: application/json" \
  -d '{
    "user_id": "user_analytics_slow",
    "amount": 879.0,
    "items": [{"product_id": "tablet", "quantity": 3}],
    "scenario": "analytics_slow",
    "idempotency_key": "smoke-analytics-slow-001"
  }'
