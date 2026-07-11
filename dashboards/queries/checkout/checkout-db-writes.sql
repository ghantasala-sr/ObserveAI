SELECT
  toStartOfMinute(timestamp) AS timestamp,
  name AS operation,
  count() AS spans,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'checkout-service'
  AND name IN ('postgres insert_order', 'postgres slow_query')
GROUP BY timestamp, operation
ORDER BY timestamp ASC, operation ASC;
