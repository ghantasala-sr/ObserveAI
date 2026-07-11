SELECT
  attributes_string['scenario'] AS scenario,
  count() AS spans,
  round(avg(duration_nano / 1000000), 2) AS avg_ms,
  round(quantile(0.99)(duration_nano / 1000000), 2) AS p99_ms
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'payment-service'
  AND name = 'payment.provider_call'
GROUP BY scenario
ORDER BY p99_ms DESC;
