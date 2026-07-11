#!/usr/bin/env bash
set -euo pipefail

for _ in {1..30}; do
  if curl -fsS http://localhost:18080/health >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS http://localhost:18080/health

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
