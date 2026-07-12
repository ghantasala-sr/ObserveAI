#!/usr/bin/env bash
set -euo pipefail

SIGNOZ_URL="${SIGNOZ_URL:-http://localhost:8080}"
MCP_ENDPOINT_URL="${MCP_ENDPOINT_URL:-http://localhost:8000/mcp}"

if [[ -f ".env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source ".env"
  set +a

  if [[ -z "${SIGNOZ_API_KEY:-}" ]]; then
    while IFS= read -r line; do
      case "${line}" in
        SIGNOZ_API_KEY=*)
          SIGNOZ_API_KEY="${line#SIGNOZ_API_KEY=}"
          SIGNOZ_API_KEY="${SIGNOZ_API_KEY#"${SIGNOZ_API_KEY%%[![:space:]]*}"}"
          SIGNOZ_API_KEY="${SIGNOZ_API_KEY%"${SIGNOZ_API_KEY##*[![:space:]]}"}"
          export SIGNOZ_API_KEY
          ;;
      esac
    done < ".env"
  fi
fi

if [[ -z "${SIGNOZ_API_KEY:-}" ]]; then
  echo "SIGNOZ_API_KEY is not set."
  echo
  echo "Set it in your local shell:"
  echo "  export SIGNOZ_API_KEY='<your-signoz-service-account-key>'"
  echo
  echo "Or add it to the local .env file, which is gitignored:"
  echo "  SIGNOZ_API_KEY='<your-signoz-service-account-key>'"
  echo
  echo "Then run:"
  echo "  bash scripts/check_mcp_auth.sh"
  exit 1
fi

echo "Checking SigNoz API key against:"
echo "  ${SIGNOZ_URL}/api/v1/service_accounts/me"

api_status="$(
  curl -sS -o /tmp/observeai-signoz-api-key-check.json -w "%{http_code}" \
    -H "SIGNOZ-API-KEY: ${SIGNOZ_API_KEY}" \
    "${SIGNOZ_URL}/api/v1/service_accounts/me"
)"

if [[ "${api_status}" != "200" ]]; then
  echo "SigNoz API key check failed with HTTP ${api_status}."
  echo "Response:"
  sed -n '1,40p' /tmp/observeai-signoz-api-key-check.json
  exit 1
fi

echo "SigNoz API key: OK"
echo
echo "Checking whether MCP endpoint accepts the auth header:"
echo "  ${MCP_ENDPOINT_URL}"

mcp_status="$(
  curl -sS --max-time 3 -o /tmp/observeai-signoz-mcp-auth-check.txt -w "%{http_code}" \
    -H "SIGNOZ-API-KEY: ${SIGNOZ_API_KEY}" \
    "${MCP_ENDPOINT_URL}" || true
)"

if [[ "${mcp_status}" == "401" ]]; then
  echo "MCP auth check failed: endpoint still returned 401."
  sed -n '1,40p' /tmp/observeai-signoz-mcp-auth-check.txt
  exit 1
fi

if [[ "${mcp_status}" == "000" ]]; then
  echo "MCP endpoint did not return a normal HTTP response within 3 seconds."
  echo "This can be OK for a streaming MCP endpoint as long as it is not returning 401."
else
  echo "MCP auth header accepted. HTTP status: ${mcp_status}"
fi
echo
echo "Next: configure your MCP client with:"
echo "  URL: ${MCP_ENDPOINT_URL}"
echo "  Header: SIGNOZ-API-KEY: <your key>"
