SELECT
  status_code_string,
  count() AS spans
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'checkout-service'
  AND name = 'checkout.workflow'
GROUP BY status_code_string
ORDER BY spans DESC;
