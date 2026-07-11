SELECT
  serviceName,
  name AS operation,
  count() AS spans,
  round(avg(duration_nano / 1000000), 2) AS avg_ms,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName IN (
    'checkout-service',
    'cart-service',
    'inventory-service',
    'payment-service',
    'ai-fraud-service'
  )
GROUP BY serviceName, operation
HAVING spans > 5
ORDER BY p99_ms DESC
LIMIT 20;
