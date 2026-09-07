# OpenShift deployment

AI-Author: Codex (OpenAI model not exposed by runtime)

This deploys the full Red Hat Offline Knowledge Portal and the separately built MCP container behind ClusterIP Services. It does not install OpenShift Lightspeed or expose a public Route. An entitled RHoKP image and access key are required; neither is included here.

## Prerequisites and installation

Use a full checkout of this repository, Bash, Python 3, OpenSSL, and an authenticated `oc` context authorized to manage the chosen namespace. Use the [GitHub Actions release image](../README.md#use-a-prebuilt-release) after it is published, or build and publish the [MCP container](../Containerfile) to your approved registry. Select immutable image digests for both images, and ensure the registry-auth file covers both registries when needed. Provide credential files with mode `0600` or `0400`; never place their values in commands or source control.

Before applying, confirm cluster identity, available memory and node image storage, existing workloads, and namespace ownership. The portal starts with a 2 GiB Solr heap, 3 GiB memory request, 6 GiB limit, and a 1 GiB temporary data volume. These are starting values, not guaranteed sizing for every image. Confirm the chosen image's index layout: mounting a PVC over an image-seeded index can hide its content. Image layers consume node storage independently of the temporary volume.

From the repository root:

```bash
oc whoami
oc version
oc get nodes
oc get namespace rhokp
# Create the namespace only if it does not exist and you own it:
oc create namespace rhokp

bash deploy/openshift/deploy.sh \
  --namespace rhokp \
  --rhokp-image "$RHOKP_IMAGE" \
  --mcp-image "$MCP_IMAGE" \
  --access-key-file /secure/rhokp-access-key \
  --registry-auth-file /secure/config.json \
  --dry-run-only
```

Set `RHOKP_IMAGE` and `MCP_IMAGE` to your approved `registry/repository@sha256:<64-hex-digest>` references. No image is selected implicitly. Add `--snapshot-date YYYY-MM-DD` if the knowledge snapshot date is known; otherwise it is reported as unknown. After reviewing dry-run results, run the same command without `--dry-run-only`. Dry-run requires an existing namespace, validates admission, and does not prove image pulls or application startup. Apply is not transactional: a later failure can leave earlier resources applied.

The installer uses isolated `rhokp-full-registry` and `rhokp-full-access-key` Secrets; do not point these at Operator-managed credentials. It strips exactly one terminal LF or CRLF from the access-key file because environment injection preserves stored bytes. It creates missing MCP bearer-token/header Secrets and preserves a matching existing pair. An inconsistent pair causes failure. Run without shell tracing; temporary credential files are private and removed on exit. Changing the access-key Secret requires restarting the portal Deployment to refresh its environment; coordinate that disruption explicitly.

The MCP implementation is baked into its image: no Python source ConfigMap is deployed. Both ServiceAccounts disable API token automount. The MCP runs non-root with a read-only root filesystem. Try the default restricted SCC for the portal first. If admission or vendor startup fails, inspect events and logs before considering a narrowly scoped SCC exception; the installer never grants one.

### Portal-only root compatibility

Some vendor portal images require UID 0. A grant of `anyuid` alone is insufficient while the Pod still specifies `runAsNonRoot: true`. First establish from Pod events, startup logs, or the selected image's documented contract that root is required, and obtain approval for this exact exception. Then an authorized administrator can grant `anyuid` only to the dedicated portal ServiceAccount:

```bash
oc adm policy add-scc-to-user anyuid -z rhokp -n rhokp
```

Re-run the installer with the same inputs plus `--portal-run-as-root --dry-run-only`, review the admission result, then apply with `--portal-run-as-root` without dry-run. The flag renders only the custom portal Pod with `runAsNonRoot: false` and `runAsUser: 0`; it does not grant SCC access. MCP remains non-root, and capability dropping, disabled privilege escalation, and seccomp remain unchanged. If startup needs additional permissions, stop and diagnose rather than granting privileged SCC or expanding this exception automatically. This flag is not appropriate for the Operator-managed portal.

Record and retain the flag in the reviewed deployment invocation while that image needs it. After a replacement image works with the default non-root settings, reapply without the flag, verify the rollout and content, and remove the now-unneeded portal-only grant:

```bash
oc adm policy remove-scc-from-user anyuid -z rhokp -n rhokp
```

Replace the namespace in both commands if deploying outside `rhokp`. Do not grant SCC access to the default or MCP ServiceAccount.

## Validation and recovery

```bash
bash deploy/openshift/validate.sh rhokp
```

Validation waits for both rollouts and streams the canonical [smoke client](../tests/smoke_mcp.py) into the MCP Pod. Its token stays in the Pod. Require authentication and Origin rejection, MCP initialization, tool discovery, real content retrieval, and unsafe-input rejection. The Service-path check from the MCP Pod proves neither a remote client's ingress nor Lightspeed tool selection. Test each intended client separately. Readiness alone does not prove useful content. These manifests have not been validated against your live cluster: admission, image startup, Ready conditions, health and actual content tests remain deployment-time gates.

For failures inspect Pod events, logs, Services and EndpointSlices. Image pull failures can indicate entitlement, authentication, digest, egress, or image storage problems. Access-key errors can involve hidden trailing bytes. MCP health failures can indicate portal DNS, Service, or Solr failure. After node recovery, verify these dependencies in order before restarting anything. No host or old deployment is removed automatically.

For updates, record current image digests and deployment configuration; test a new snapshot separately before changing images. Roll back by reapplying the previous reviewed image configuration. Retain matching credentials and old migration endpoints until the replacement passes real client requests. Namespace deletion is not a routine rollback.

## Optional OpenShift Lightspeed integration

Custom MCP configuration is release-dependent. Inspect the installed owner API first:

```bash
oc explain olsconfig.spec.mcpServers --recursive
oc explain olsconfig.spec.featureGates
```

Only continue when it supports the `url`, `timeout`, and secret-backed `headers` shape produced by [merge_olsconfig.py](../deploy/openshift/merge_olsconfig.py). That helper preserves unrelated MCP servers and feature gates and replaces only the entry named `rhokp`. Back up the owner configuration securely and inspect the generated patch before applying:

```bash
umask 077
oc get olsconfig cluster -o json > /secure/olsconfig-before.json
python3 deploy/openshift/merge_olsconfig.py --namespace rhokp \
  < /secure/olsconfig-before.json > /secure/rhokp-ols-patch.json
oc patch olsconfig cluster --type=merge \
  --patch-file=/secure/rhokp-ols-patch.json --dry-run=server
# Apply the same command without --dry-run only after reviewing the result.
```

The referenced `rhokp-mcp-auth` Secret must exist in the namespace where the Lightspeed Operator resolves Secret references, with a `header` key containing `Bearer ` followed by the same server token. Transfer only that Secret via a protected administrative workflow, never by printing its value. Do not copy the registry, portal-access or server-token Secrets to the Lightspeed namespace unnecessarily.

For cross-namespace callers, add a separate NetworkPolicy allowing TCP 18081 to MCP Pods. Its single `from` item must combine a namespace selector (`kubernetes.io/metadata.name: <lightspeed-namespace>`) AND a Pod selector matching the actual Lightspeed application-server labels. Separate items are OR, not AND. Verify labels live. The bundled same-namespace rule expects `app.kubernetes.io/component: application-server` and `app.kubernetes.io/part-of: openshift-lightspeed`. Never broadly permit all namespaces to fix a timeout. Cluster egress policies may also need a narrowly scoped allowance.

Modify `OLSConfig`, not Operator-generated Deployments or ConfigMaps. After reconciliation, send an approved non-sensitive question explicitly requesting `rhokp_search`. Require a successful tool result, non-empty answer, and correlated MCP/Lightspeed logs; a Ready owner or HTTP 200 alone is insufficient. An external LLM may receive retrieved content, so approve that data flow first. Optional tool filtering must use fields exposed by the installed CRD and be followed by the same end-to-end test.

### Optional managed-portal storage tuning

Lightspeed's managed RHoKP operand and its `portal-rag` collection are separate from this full portal and its `portal` collection. Do not compare RAG chunk counts with full-document counts. If the installed CRD exposes `spec.ols.deployment.rhokp.resources`, inspect the generated volume and measure actual use before tuning. For a small measured workload, a 2 GiB ephemeral-storage request may be a reasonable trial, not a universal default. Some releases derive the managed `emptyDir.sizeLimit` from this request and replace the entire resources object, so preserve current CPU and memory requests rather than submitting only the storage key. Save the exact previous resources object, server-dry-run the owner change, and verify the generated request, volume size, rollout, nonzero `portal-rag` content and real query. Restore the previous owner resources if any gate fails. Never patch the managed Deployment directly.
