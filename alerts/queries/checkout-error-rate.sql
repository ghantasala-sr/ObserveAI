SELECT
  toFloat64(if(count() = 0, 0, round(countIf(status_code = 2) / count() * 100, 2))) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName = 'checkout-service'
  AND name = 'checkout.workflow';
