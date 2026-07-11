SELECT
  toFloat64(count()) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName IN (
    'traffic-generator',
    'checkout-service',
    'cart-service',
    'inventory-service',
    'payment-service',
    'ai-fraud-service'
  );
