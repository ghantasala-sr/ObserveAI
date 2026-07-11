SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  name AS operation,
  toFloat64(round(quantile(0.99)(duration_nano / 1000000), 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND name LIKE 'redis%'
GROUP BY ts, operation
ORDER BY ts ASC, operation ASC;
