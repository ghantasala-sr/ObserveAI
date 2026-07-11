#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:18080}"
TOTAL_REQUESTS="${TOTAL_REQUESTS:-80}"

for _ in {1..30}; do
  if curl -fsS "$BASE_URL/health" >/dev/null; then
    break
  fi
  sleep 1
done

curl -fsS "$BASE_URL/health"
echo

success=0
expected_failures=0
unexpected=0

run_checkout() {
  local index="$1"
  local scenario="$2"
  local amount="$3"
  local quantity="$4"
  local expected_status="$5"

  local status
  status=$(
    curl -sS -o /tmp/observeai-big-smoke-response.json -w "%{http_code}" \
      -X POST "$BASE_URL/checkout" \
      -H "content-type: application/json" \
      -d "{
        \"user_id\": \"load_user_$((index % 12))\",
        \"amount\": $amount,
        \"items\": [{\"product_id\": \"item_$((index % 5))\", \"quantity\": $quantity}],
        \"scenario\": \"$scenario\",
        \"idempotency_key\": \"big-smoke-$index-$scenario\"
      }"
  )

  if [[ "$status" == "$expected_status" ]]; then
    if [[ "$status" =~ ^2 ]]; then
      success=$((success + 1))
    else
      expected_failures=$((expected_failures + 1))
    fi
    printf "ok     %03d scenario=%-16s status=%s\n" "$index" "$scenario" "$status"
  else
    unexpected=$((unexpected + 1))
    printf "bad    %03d scenario=%-16s expected=%s actual=%s response=" "$index" "$scenario" "$expected_status" "$status"
    cat /tmp/observeai-big-smoke-response.json
    echo
  fi
}

for index in $(seq 1 "$TOTAL_REQUESTS"); do
  case $((index % 10)) in
    0)
      run_checkout "$index" "payment_fail" "249.0" "1" "502"
      ;;
    1)
      run_checkout "$index" "normal" "99.0" "1" "200"
      ;;
    2)
      run_checkout "$index" "payment_slow" "349.0" "2" "200"
      ;;
    3)
      run_checkout "$index" "fraud_ai_slow" "1200.0" "6" "200"
      ;;
    4)
      run_checkout "$index" "inventory_fail" "179.0" "1" "409"
      ;;
    5)
      run_checkout "$index" "normal" "799.0" "1" "200"
      ;;
    6)
      run_checkout "$index" "provider_timeout" "629.0" "2" "502"
      ;;
    7)
      run_checkout "$index" "normal" "45.0" "1" "200"
      ;;
    8)
      run_checkout "$index" "fraud_ai_slow" "950.0" "4" "200"
      ;;
    9)
      run_checkout "$index" "payment_slow" "540.0" "3" "200"
      ;;
  esac
done

echo
echo "ObserveAI big smoke complete"
echo "successful checkouts: $success"
echo "expected failures:    $expected_failures"
echo "unexpected results:   $unexpected"
echo
echo "Open SigNoz: http://localhost:8080"
echo "Use time range: Last 15 minutes"
echo "Look for services: checkout-service, payment-service, inventory-service, ai-fraud-service"

if [[ "$unexpected" -gt 0 ]]; then
  exit 1
fi
