SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  serviceName,
  toFloat64(round(countIf(status_code = 2) / count() * 100, 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName IN (
    'checkout-service',
    'inventory-service',
    'payment-service',
    'ai-fraud-service'
  )
GROUP BY ts, serviceName
ORDER BY ts ASC, serviceName ASC;
