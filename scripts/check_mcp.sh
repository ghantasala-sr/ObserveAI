#!/usr/bin/env bash
set -euo pipefail

MCP_LIVEZ_URL="${MCP_LIVEZ_URL:-http://localhost:8000/livez}"
MCP_ENDPOINT_URL="${MCP_ENDPOINT_URL:-http://localhost:8000/mcp}"

echo "Checking SigNoz MCP health endpoint:"
echo "  ${MCP_LIVEZ_URL}"

if curl -fsS "${MCP_LIVEZ_URL}" >/dev/null; then
  echo "SigNoz MCP livez: OK"
  echo "MCP endpoint should be available at:"
  echo "  ${MCP_ENDPOINT_URL}"
else
  echo "SigNoz MCP livez: FAILED"
  echo
  echo "If you use Foundry, enable MCP in casting.yaml:"
  echo
  echo "spec:"
  echo "  mcp:"
  echo "    spec:"
  echo "      enabled: true"
  echo
  echo "Then run:"
  echo "  foundryctl cast -f casting.yaml"
  exit 1
fi
