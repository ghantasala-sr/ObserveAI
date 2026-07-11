SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS interval,
  toFloat64(round(countIf(status_code = 2) / count() * 100, 2)) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName = 'checkout-service'
  AND name = 'checkout.workflow'
GROUP BY interval
ORDER BY interval ASC;
