SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS interval,
  toFloat64(count()) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName = 'ai-fraud-service'
  AND name = 'kafka publish fraud.check.dlq'
GROUP BY interval
ORDER BY interval ASC;
