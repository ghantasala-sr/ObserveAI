SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS interval,
  toFloat64(round(quantile(0.99)(duration_nano / 1000000), 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND name = 'postgres slow_query'
GROUP BY interval
ORDER BY interval ASC;
