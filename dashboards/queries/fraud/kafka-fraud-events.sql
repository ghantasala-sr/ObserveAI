SELECT
  toStartOfInterval(timestamp, INTERVAL 1 MINUTE) AS ts,
  concat(serviceName, ' ', name) AS series,
  toFloat64(count()) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND name IN (
    'kafka publish fraud.check.requested',
    'kafka publish fraud.check.completed',
    'fraud.inference'
  )
GROUP BY ts, serviceName, name
ORDER BY ts ASC, serviceName ASC, name ASC;
