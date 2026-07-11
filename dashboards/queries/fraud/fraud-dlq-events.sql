SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  'fraud.check.dlq events' AS series,
  toFloat64(count()) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'ai-fraud-service'
  AND name = 'kafka publish fraud.check.dlq'
GROUP BY ts
ORDER BY ts ASC;
