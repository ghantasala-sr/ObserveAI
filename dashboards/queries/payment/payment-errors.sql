SELECT
  attributes_string['scenario'] AS scenario,
  countIf(status_code = 2) AS error_spans,
  count() AS total_spans
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'payment-service'
  AND name = 'payment.provider_call'
GROUP BY scenario
ORDER BY error_spans DESC, total_spans DESC;
