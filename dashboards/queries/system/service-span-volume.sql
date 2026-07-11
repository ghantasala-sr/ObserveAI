SELECT
  toStartOfMinute(timestamp) AS timestamp,
  serviceName,
  count() AS spans
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName IN (
    'traffic-generator',
    'checkout-service',
    'cart-service',
    'inventory-service',
    'payment-service',
    'ai-fraud-service'
  )
GROUP BY timestamp, serviceName
ORDER BY timestamp ASC, serviceName ASC;
