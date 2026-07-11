SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS interval,
  toFloat64(max(attributes_number['kafka.consumer.lag_estimate'])) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName = 'ai-fraud-service'
  AND name = 'fraud.inference'
  AND mapContains(attributes_number, 'kafka.consumer.lag_estimate')
GROUP BY interval
ORDER BY interval ASC;
