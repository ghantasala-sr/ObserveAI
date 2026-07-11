SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  'checkout p99' AS series,
  toFloat64(round(quantile(0.99)(duration_nano / 1000000), 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'checkout-service'
  AND name = 'checkout.workflow'
GROUP BY ts
ORDER BY ts ASC;
