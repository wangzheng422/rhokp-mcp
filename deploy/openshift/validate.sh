#!/usr/bin/env bash
# AI-Author: Codex (OpenAI model not exposed by runtime)
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
namespace=${1:-rhokp}
[[ "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || exit 2
oc -n "$namespace" rollout status deployment/rhokp --timeout=1800s
oc -n "$namespace" rollout status deployment/rhokp-mcp --timeout=300s
# The token stays inside the Pod. This also tests Service selection and the
# MCP-to-portal path, but does not prove a different namespace's ingress.
oc -n "$namespace" exec -i deployment/rhokp-mcp -- python3 - \
  --endpoint http://rhokp-mcp/mcp \
  --token-file /var/run/secrets/rhokp-mcp/token \
  < "$script_dir/../../tests/smoke_mcp.py"
oc -n "$namespace" get deploy,svc,pod,endpointslice -l app.kubernetes.io/part-of=rhokp-mcp
