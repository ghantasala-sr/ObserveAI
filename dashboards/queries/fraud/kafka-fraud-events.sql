SELECT
  toStartOfMinute(timestamp) AS minute,
  serviceName,
  name AS operation,
  count() AS spans,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND name IN (
    'kafka publish fraud.check.requested',
    'kafka publish fraud.check.completed',
    'fraud.inference'
  )
GROUP BY minute, serviceName, operation
ORDER BY minute ASC, serviceName ASC, operation ASC;
