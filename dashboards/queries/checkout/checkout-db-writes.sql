SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  name AS operation,
  toFloat64(round(quantile(0.99)(duration_nano / 1000000), 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'checkout-service'
  AND name IN ('postgres insert_order', 'postgres slow_query')
GROUP BY ts, operation
ORDER BY ts ASC, operation ASC;
