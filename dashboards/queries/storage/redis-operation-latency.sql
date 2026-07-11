SELECT
  toStartOfMinute(timestamp) AS minute,
  name AS operation,
  round(quantile(0.50)(duration_nano / 1000000), 2) AS p50_ms,
  round(quantile(0.90)(duration_nano / 1000000), 2) AS p90_ms,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND name LIKE 'redis%'
GROUP BY minute, operation
ORDER BY minute ASC, operation ASC;
