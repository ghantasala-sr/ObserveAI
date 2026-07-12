SELECT
  if(status_code = 2, 'failed', 'sent') AS notification_status,
  toFloat64(count()) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'notification-service'
  AND name = 'notification.send'
GROUP BY notification_status
ORDER BY value DESC;
