SELECT
  toStartOfMinute(timestamp) AS minute,
  serviceName,
  countIf(status_code = 2) AS error_spans,
  count() AS total_spans,
  round(error_spans / total_spans * 100, 2) AS error_span_percent
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName IN (
    'checkout-service',
    'inventory-service',
    'payment-service',
    'ai-fraud-service'
  )
GROUP BY minute, serviceName
ORDER BY minute ASC, serviceName ASC;
