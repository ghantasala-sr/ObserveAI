SELECT
  name AS operation,
  count() AS spans,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND name LIKE 'redis%'
GROUP BY operation
ORDER BY spans DESC;
