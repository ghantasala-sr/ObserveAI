SELECT
  attributes_string['fraud.decision'] AS decision,
  count() AS spans,
  round(avg(attributes_number['fraud.risk_score']), 3) AS avg_risk_score
FROM signoz_traces.distributed_signoz_index_v3
WHERE timestamp >= now() - INTERVAL 15 MINUTE
  AND serviceName = 'ai-fraud-service'
  AND name = 'fraud.inference'
GROUP BY decision
ORDER BY spans DESC;
