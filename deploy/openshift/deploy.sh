#!/usr/bin/env bash
# AI-Author: Codex (OpenAI gpt-5.6-sol)
# AI-Author: Codex (OpenAI model not exposed by runtime)
set -euo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

namespace='rhokp'
access_key_file=''
registry_auth_file=''
registry_secret_name='rhokp-full-registry'
access_key_secret_name='rhokp-full-access-key'
rhokp_image=''
mcp_image=''
snapshot_date='unknown'
dry_run_only='false'
portal_run_as_root='false'

usage() {
  echo "Usage: $0 --access-key-file PATH --rhokp-image IMAGE@sha256:DIGEST --mcp-image IMAGE@sha256:DIGEST [--registry-auth-file PATH] [--namespace NAME] [--registry-secret-name NAME] [--access-key-secret-name NAME] [--snapshot-date YYYY-MM-DD] [--dry-run-only] [--portal-run-as-root]" >&2
}

while (($#)); do
  case "$1" in
    --namespace) namespace=${2:?}; shift 2 ;;
    --access-key-file) access_key_file=${2:?}; shift 2 ;;
    --registry-auth-file) registry_auth_file=${2:?}; shift 2 ;;
    --registry-secret-name) registry_secret_name=${2:?}; shift 2 ;;
    --access-key-secret-name) access_key_secret_name=${2:?}; shift 2 ;;
    --rhokp-image) rhokp_image=${2:?}; shift 2 ;;
    --mcp-image) mcp_image=${2:?}; shift 2 ;;
    --snapshot-date) snapshot_date=${2:?}; shift 2 ;;
    --dry-run-only) dry_run_only='true'; shift ;;
    --portal-run-as-root) portal_run_as_root='true'; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ "$namespace" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || { echo 'invalid namespace' >&2; exit 2; }
[[ "$registry_secret_name" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || { echo 'invalid registry Secret name' >&2; exit 2; }
[[ "$access_key_secret_name" =~ ^[a-z0-9]([-a-z0-9]*[a-z0-9])?$ ]] || { echo 'invalid access-key Secret name' >&2; exit 2; }
[[ "$registry_secret_name" != "$access_key_secret_name" ]] || { echo 'registry and access-key Secret names must differ' >&2; exit 2; }
[[ "$rhokp_image" =~ ^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$ ]] || { echo 'RHoKP image must be digest-pinned' >&2; exit 2; }
[[ "$mcp_image" =~ ^[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}$ ]] || { echo 'MCP image must be digest-pinned' >&2; exit 2; }
[[ "$snapshot_date" == unknown || "$snapshot_date" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo 'invalid snapshot date' >&2; exit 2; }
[[ -f "$access_key_file" && -s "$access_key_file" ]] || { echo 'RHoKP access-key file is missing or empty' >&2; exit 2; }

check_secret_file() {
  local path=$1 mode
  mode=$(stat -c '%a' "$path")
  case "$mode" in
    400|600) ;;
    *) echo "credential file must have mode 0400 or 0600: $path" >&2; exit 2 ;;
  esac
}

check_secret_file "$access_key_file"
if [[ -n "$registry_auth_file" ]]; then
  [[ -f "$registry_auth_file" && -s "$registry_auth_file" ]] || { echo 'registry auth file is missing or empty' >&2; exit 2; }
  check_secret_file "$registry_auth_file"
  python3 -c 'import json,sys; value=json.load(open(sys.argv[1])); assert isinstance(value.get("auths"),dict) and value["auths"]' "$registry_auth_file"
fi

command -v oc >/dev/null
command -v openssl >/dev/null
oc whoami >/dev/null

temporary_dir=$(mktemp -d /tmp/deploy-rhokp-openshift.XXXXXX)
chmod 700 "$temporary_dir"
trap 'rm -rf -- "$temporary_dir"' EXIT

apply_manifest() {
  local manifest=$1
  oc apply --server-side --dry-run=server -f "$manifest"
  if [[ "$dry_run_only" == 'false' ]]; then
    oc apply --server-side -f "$manifest"
  fi
}

# Kubernetes secretKeyRef injects file bytes exactly. Accept a conventional
# final LF/CRLF from handoff files, but never include it in ACCESS_KEY.
python3 "$script_dir/normalize_access_key.py" \
  "$access_key_file" "$temporary_dir/access-key"

cat > "$temporary_dir/namespace.yaml" <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $namespace
  labels:
    app.kubernetes.io/part-of: rhokp-mcp
EOF
if oc get namespace "$namespace" >/dev/null 2>&1; then
  echo "namespace_action=preserved name=$namespace"
else
  if [[ "$dry_run_only" == 'true' ]]; then
    echo 'dry-run-only requires the target namespace to exist' >&2
    exit 2
  fi
  apply_manifest "$temporary_dir/namespace.yaml"
fi

if [[ -n "$registry_auth_file" ]]; then
  oc -n "$namespace" create secret generic "$registry_secret_name" \
    --type=kubernetes.io/dockerconfigjson \
    --from-file=.dockerconfigjson="$registry_auth_file" \
    --dry-run=client -o yaml > "$temporary_dir/registry-secret.yaml"
  apply_manifest "$temporary_dir/registry-secret.yaml"
elif ! oc -n "$namespace" get secret "$registry_secret_name" >/dev/null 2>&1; then
  echo "Secret/$registry_secret_name is absent; provide --registry-auth-file" >&2
  exit 2
fi

oc -n "$namespace" create secret generic "$access_key_secret_name" \
  --from-file=ACCESS_KEY="$temporary_dir/access-key" \
  --dry-run=client -o yaml > "$temporary_dir/access-key-secret.yaml"
apply_manifest "$temporary_dir/access-key-secret.yaml"

server_secret=no
header_secret=no
oc -n "$namespace" get secret rhokp-mcp-server-auth >/dev/null 2>&1 && server_secret=yes
oc -n "$namespace" get secret rhokp-mcp-auth >/dev/null 2>&1 && header_secret=yes
if [[ "$server_secret" == no && "$header_secret" == no ]]; then
  umask 077
  openssl rand -hex 32 > "$temporary_dir/token"
  { printf 'Bearer '; tr -d '\r\n' < "$temporary_dir/token"; printf '\n'; } > "$temporary_dir/header"
elif [[ "$server_secret" == no ]]; then
  oc -n "$namespace" get secret rhokp-mcp-auth -o jsonpath='{.data.header}' | base64 --decode > "$temporary_dir/header"
  grep -Eq '^Bearer [^[:space:]]{32,}[[:space:]]*$' "$temporary_dir/header" || { echo 'existing Lightspeed MCP header is invalid' >&2; exit 3; }
  sed -e 's/^Bearer //' -e 's/[[:space:]]*$//' "$temporary_dir/header" > "$temporary_dir/token"
  echo 'mcp_auth_migration=derived_server_token_from_existing_header'
elif [[ "$header_secret" == no ]]; then
  oc -n "$namespace" get secret rhokp-mcp-server-auth -o jsonpath='{.data.token}' | base64 --decode > "$temporary_dir/token"
  grep -Eq '^[^[:space:]]{32,}[[:space:]]*$' "$temporary_dir/token" || { echo 'existing MCP server token is invalid' >&2; exit 3; }
  { printf 'Bearer '; tr -d '\r\n' < "$temporary_dir/token"; printf '\n'; } > "$temporary_dir/header"
  echo 'mcp_auth_migration=derived_lightspeed_header_from_existing_token'
else
  oc -n "$namespace" get secret rhokp-mcp-server-auth -o jsonpath='{.data.token}' | base64 --decode > "$temporary_dir/token"
  oc -n "$namespace" get secret rhokp-mcp-auth -o jsonpath='{.data.header}' | base64 --decode > "$temporary_dir/header"
  expected_header=$( { printf 'Bearer '; tr -d '\r\n' < "$temporary_dir/token"; } )
  actual_header=$(tr -d '\r\n' < "$temporary_dir/header")
  [[ "$actual_header" == "$expected_header" ]] || { echo 'existing MCP server/header Secrets do not match' >&2; exit 3; }
  echo 'mcp_auth_action=preserved'
fi
if [[ "$server_secret" == no ]]; then
  oc -n "$namespace" create secret generic rhokp-mcp-server-auth \
    --from-file=token="$temporary_dir/token" \
    --dry-run=client -o yaml > "$temporary_dir/rhokp-mcp-server-auth.yaml"
  apply_manifest "$temporary_dir/rhokp-mcp-server-auth.yaml"
fi
if [[ "$header_secret" == no ]]; then
  oc -n "$namespace" create secret generic rhokp-mcp-auth \
    --from-file=header="$temporary_dir/header" \
    --dry-run=client -o yaml > "$temporary_dir/rhokp-mcp-auth.yaml"
  apply_manifest "$temporary_dir/rhokp-mcp-auth.yaml"
fi
[[ "$server_secret" == no || "$header_secret" == no ]] && echo 'mcp_auth_action=created_missing_secret'


rhokp_digest=${rhokp_image##*@}
sed \
  -e "s|__RHOKP_IMAGE__|$rhokp_image|g" \
  -e "s|__RHOKP_DIGEST__|$rhokp_digest|g" \
  -e "s|__MCP_IMAGE__|$mcp_image|g" \
  -e "s|__SNAPSHOT_DATE__|$snapshot_date|g" \
  -e "s|__REGISTRY_SECRET__|$registry_secret_name|g" \
  -e "s|__ACCESS_KEY_SECRET__|$access_key_secret_name|g" \
  "$script_dir/rhokp-openshift.yaml" > "$temporary_dir/rhokp-openshift.yaml"
if [[ "$portal_run_as_root" == 'true' ]]; then
  # Only the portal has this Pod-level field; MCP container settings stay intact.
  sed -i 's/^        runAsNonRoot: true$/        runAsNonRoot: false\n        runAsUser: 0/' "$temporary_dir/rhokp-openshift.yaml"
  echo 'portal_uid_exception=requested_root_existing_scoped_scc_required' >&2
fi
oc -n "$namespace" apply --server-side --dry-run=server -f "$temporary_dir/rhokp-openshift.yaml"
if [[ "$dry_run_only" == 'true' ]]; then
  echo "deployment_dry_run=passed namespace=$namespace"
  exit 0
fi
oc -n "$namespace" apply --server-side -f "$temporary_dir/rhokp-openshift.yaml"

oc -n "$namespace" get secret "$registry_secret_name" "$access_key_secret_name" rhokp-mcp-server-auth rhokp-mcp-auth \
  -o go-template='{{range .items}}{{.metadata.name}}{{"\t"}}{{.type}}{{"\t"}}{{range $k,$v := .data}}{{$k}}{{","}}{{end}}{{"\n"}}{{end}}'
oc -n "$namespace" get deploy,svc -l app.kubernetes.io/part-of=rhokp-mcp
echo "deployment_applied=yes namespace=$namespace"
