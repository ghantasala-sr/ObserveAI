SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  name AS series,
  toFloat64(round(quantile(0.99)(duration_nano / 1000000), 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'analytics-service'
  AND name IN ('analytics.process_fraud_completed', 'analytics.process_fraud_dlq')
GROUP BY ts, series
ORDER BY ts ASC, series ASC;
