# ObserveAI + SigNoz MCP Learning Guide

This guide is for learning how the SigNoz MCP server fits into an observability workflow.

ObserveAI already sends real traces, logs, and metrics to SigNoz. The MCP layer lets an AI assistant query that observability data through SigNoz instead of making you manually click through every trace, dashboard, and alert.

## Mental Model

```text
ObserveAI services
  -> OpenTelemetry Collector
  -> SigNoz
  -> SigNoz MCP Server
  -> AI assistant / IDE agent
```

Use ObserveAI to generate incidents. Use SigNoz to store and visualize the evidence. Use MCP to let an AI assistant investigate that evidence.

## What MCP Should Help Us Ask

Good first prompts after ObserveAI is running:

```text
Show me recent traces for checkout-service.
```

```text
Find slow payment-service spans in the last 30 minutes and summarize the bottleneck.
```

```text
Investigate the latest payment_slow scenario. Which span owns most of the latency?
```

```text
Check whether ai-fraud-service has Kafka consumer lag or DLQ-related errors.
```

```text
Suggest dashboard panels and alerts for ObserveAI checkout, payment, Kafka, and AI fraud workflows.
```

## Enable SigNoz MCP With Foundry

SigNoz now recommends Foundry for self-hosted Docker installs. The official Docker guide says Foundry can deploy the SigNoz MCP server alongside SigNoz, but MCP is disabled by default.

In your SigNoz `casting.yaml`, add:

```yaml
apiVersion: v1alpha1
kind: Installation
metadata:
  name: signoz
spec:
  deployment:
    flavor: compose
    mode: docker
  mcp:
    spec:
      enabled: true
```

Then run:

```bash
foundryctl cast -f casting.yaml
```

Verify MCP is alive:

```bash
curl -fsS http://localhost:8000/livez && echo " OK"
```

The MCP HTTP endpoint is:

```text
http://localhost:8000/mcp
```

## Create A SigNoz API Key

In SigNoz:

```text
Settings -> Service Accounts -> Create service account -> Keys -> Add Key
```

Do not commit this key.

## Connect Codex To Local SigNoz MCP

For HTTP mode:

```bash
codex mcp add signoz --url http://localhost:8000/mcp
```

Or add this to a Codex config file:

```toml
[mcp_servers.signoz]
url = "http://localhost:8000/mcp"
```

If using a self-hosted MCP server that requires a header/API key, configure it in your local user config only. Do not commit secrets.

## Connect Claude Code To Local SigNoz MCP

```bash
claude mcp add --scope user --transport http signoz http://localhost:8000/mcp \
  --header "SIGNOZ-API-KEY: <your-api-key>"
```

Then run `/mcp` inside Claude Code and confirm `signoz` is connected.

## Connect Cursor / VS Code

For HTTP mode:

```json
{
  "mcpServers": {
    "signoz": {
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

VS Code style:

```json
{
  "servers": {
    "signoz": {
      "type": "http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

## ObserveAI Practice Workflow

1. Start SigNoz with MCP enabled.
2. Start ObserveAI.
3. Open ObserveAI UI:

```text
http://127.0.0.1:18082
```

4. Trigger scenarios:

```text
payment_slow
kafka_consumer_slow
poison_message
db_slow
notification_fail
```

5. Copy the Trace Helper query from the UI and confirm it works in SigNoz.
6. Ask the MCP-connected assistant to investigate the same scenario in natural language.

## Learning Goal

We are not using ObserveAI as the final hackathon entry. This MCP integration is practice.

For the hackathon, the separate project should use MCP more deeply:

```text
AI agent observability
SigNoz MCP investigation
dashboards
alerts
trace/log/metric correlation
```

## Official References

- SigNoz Docker + Foundry install: https://signoz.io/docs/install/docker/
- SigNoz MCP server guide: https://signoz.io/docs/ai/signoz-mcp-server/
- SigNoz AI use cases: https://signoz.io/docs/ai/use-cases/
