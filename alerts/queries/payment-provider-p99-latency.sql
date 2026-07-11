SELECT
  toFloat64(if(count() = 0, 0, round(quantile(0.99)(duration_nano / 1000000), 2))) AS value
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 5 MINUTE
  AND serviceName = 'payment-service'
  AND name = 'payment.provider_call';
