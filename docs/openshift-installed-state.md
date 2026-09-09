# What Is in the Cluster After Installation on OpenShift?

AI-Author: Codex (OpenAI model not exposed by runtime)

This document starts with **what the installation creates**, then explains the configuration. For the procedure, see the [OpenShift installation guide](openshift.md). It describes the repository's [installation script](../deploy/openshift/deploy.sh) and [resource template](../deploy/openshift/rhokp-openshift.yaml), not a live snapshot of a particular cluster. Configuration fields may differ between Lightspeed versions.

The examples assume this project is installed in the `rhokp` namespace and optional OpenShift Lightspeed is installed in `openshift-lightspeed`. If you change namespaces, update Service addresses, Secret locations, and NetworkPolicies accordingly.

## 1. Three Separate Roles, Not One All-in-One Installation

| Role | Purpose | Installation or configuration responsibility |
|---|---|---|
| Full RHoKP | Retrieval backend containing offline knowledge, using the Solr `portal` collection | This project's base installation |
| RHoKP MCP adapter | Exposes backend retrieval as read-only tools for AI clients; it is not an LLM | This project's base installation |
| OpenShift Lightspeed | AI assistant users query in the Console; connects to a model and can call MCP tools | Install the Operator and configure a model separately, then add the optional integration |

**Running this project's `deploy.sh` creates only the first two components; it does not automatically add a Console chat interface.** Other MCP clients can use this knowledge base without Lightspeed. The base installation does not require an LLM API key.

With Lightspeed integrated, a tool-based retrieval follows this path: the user asks a question in the Console → the Lightspeed application service works with the configured model to select a tool → `rhokp-mcp` → `rhokp` → knowledge excerpts are returned → Lightspeed and the model generate an answer. The model may not choose a tool for every question; verify this with a real question-and-answer test.

“Offline knowledge base” means only that retrieved content comes from an offline snapshot; **it does not mean the entire AI question-and-answer workflow is disconnected from the network**. If Lightspeed uses an external model, questions and retrieved excerpts may be sent to that model. Obtain approval beforehand.

## 2. Resources Created by the Base Installation

The following are the default names. The installation preserves an existing namespace or creates it if absent; `--dry-run-only` requires the namespace to exist beforehand.

| Namespace | Resource | Purpose |
|---|---|---|
| `rhokp` | Deployment `rhokp` | One replica running the licensed RHoKP image; `Recreate` update strategy |
| `rhokp` | Deployment `rhokp-mcp` | One replica running this project's MCP image; a rolling update may temporarily add one Pod |
| `rhokp` | Service `rhokp` | ClusterIP, `8080 → Pod 8080` |
| `rhokp` | Service `rhokp-mcp` | ClusterIP, `80 → Pod 18081` |
| `rhokp` | ServiceAccounts `rhokp`, `rhokp-mcp` | Two dedicated runtime identities; API token automounting is disabled for Pods in both Deployments |
| `rhokp` | Secret `rhokp-full-registry` | Registry pull credentials referenced by both Pods; applied when a credentials file is provided, otherwise must already exist |
| `rhokp` | Secret `rhokp-full-access-key` | RHoKP content access credentials, not an LLM API key |
| `rhokp` | Secret `rhokp-mcp-server-auth` | Token the MCP server uses to authenticate requests |
| `rhokp` | Secret `rhokp-mcp-auth` | Complete Authorization header used by clients |
| `rhokp` | NetworkPolicy `rhokp-ingress` | Allows MCP Pods in the same namespace to reach RHoKP on port 8080 |
| `rhokp` | NetworkPolicy `rhokp-mcp-ingress` | Allows MCP / Lightspeed application Pods with matching labels in the same namespace to reach MCP on port 18081 |

Kubernetes generates ReplicaSets, Pods, and EndpointSlices from these resources, usually with name suffixes. Do not use example suffixes as acceptance criteria.

The base installation **does not create** a Route, Ingress, PVC, LLM service, Lightspeed Operator, `OLSConfig`, or cross-namespace allow rules for Lightspeed. It does not automatically grant `anyuid`. MCP code is included in the image, not injected through a source-code ConfigMap.

## 3. Key Configuration of the Two Deployments

The table below shows the template's effective configuration. Installation arguments must specify images by digest; there are no implicit default images.

| Setting | `rhokp` | `rhokp-mcp` |
|---|---|---|
| Image | Licensed RHoKP `image@sha256:…` | MCP `image@sha256:…` published by this project or built locally |
| Backend connection | Is itself the knowledge backend | `RHOKP_BASE_URL=http://rhokp:8080` |
| Source links | Not applicable | `RHOKP_SOURCE_BASE_URL=http://rhokp:8080`; the default is an internal cluster address, usually inaccessible from a desktop browser |
| Authentication input | Secret key `ACCESS_KEY` injected into an environment variable of the same name | `MCP_TOKEN_FILE=/var/run/secrets/rhokp-mcp/token`, mounted through a Secret volume |
| Other settings | `ONLINE_VIEW=false`, `SOLR_MEM=2g` | `RHOKP_IMAGE_DIGEST` comes from the image argument; the snapshot date is `unknown` if unspecified |
| CPU request / limit | `2 / 4` | `50m / 500m` |
| Memory request / limit | `3Gi / 6Gi` | `96Mi / 512Mi` |
| Temporary volume | `/var/solr/data`, `emptyDir.sizeLimit: 1Gi` | `/tmp`, `emptyDir.sizeLimit: 64Mi` |
| ephemeral-storage request / limit | `1Gi / 10Gi` | Not explicitly set in the template |
| Readiness probe | HTTP query against the `portal` collection | HTTP `/healthz` |

These are starting values, not capacity guarantees for every knowledge image. `emptyDir` is not a persistent backup; data can be lost when a Pod is replaced. Node disk space consumed by knowledge image layers is separate from the 1 GiB temporary volume capacity. Do not mount a PVC over the image's bundled index path without inspection, as it could hide the content.

Both workloads run as non-root by default, disallow privilege escalation, and drop capabilities; MCP also uses a read-only root filesystem. If a vendor image genuinely requires root, first collect evidence and obtain approval, then use the portal-only exception described in [root compatibility](openshift.md#portal-only-root-compatibility).

The complete resources to apply are in [rhokp-openshift.yaml](../deploy/openshift/rhokp-openshift.yaml), not in this document's excerpts. The script substitutes image, Secret name, and snapshot placeholders, then applies them with `oc -n <namespace> apply --server-side`. Secrets are generated separately from protected files. The script performs server-side dry runs before applying resources. The process is not transactional: a later failure may leave previously created resources in place.

The script output `deployment_applied=yes` means only that resources were applied. **It does not wait for rollout or establish that installation acceptance checks passed.** The runtime and real-content checks below must still be completed separately.

## 4. Keep Credentials for Different Purposes Separate

| Secret | Key in `data` | Consumer |
|---|---|---|
| `rhokp-full-registry` | `.dockerconfigjson` | kubelet, for image pulls |
| `rhokp-full-access-key` | `ACCESS_KEY` | RHoKP container |
| `rhokp-mcp-server-auth` | `token` | MCP server; contains the token itself |
| `rhokp-mcp-auth` | `header` | MCP clients; contains `Bearer ` followed by the same token |
| `llm-api-credentials` (example below only) | `apitoken` | Lightspeed, to connect to the selected model; not created by the base installation |

The `header` value must be `Bearer ` followed by the server's `token`. The installer generates missing authentication Secrets or derives a missing Secret from its existing counterpart. It preserves an existing pair and fails if their contents are inconsistent. After updating the RHoKP access key, coordinate a restart of the portal Deployment; its environment variable does not update automatically.

For cross-namespace integration, **also place a Secret named `rhokp-mcp-auth`, with the same `header` key, in the namespace where Lightspeed resolves Secrets**. Having it only in `rhokp` is insufficient. Transfer it through a protected administrative process without printing values in the terminal. Do not copy the registry, portal access-key, or server-side token Secrets alongside it; they are not required there.

## 5. What Should OLSConfig Look Like with Lightspeed Integration?

### 5.1 Resource Ownership

`OLSConfig/cluster` is the Operator's configuration entry point. It is cluster-scoped, so omit `metadata.namespace`. The Operator uses it to reconcile its application service, Console integration, and other components, such as retrieval where supported by the installed version. **Change the owner configuration, not Operator-generated Deployments or ConfigMaps directly.** The exact names and number of generated resources depend on the installed version.

This project provides only a [configuration merge helper](../deploy/openshift/merge_olsconfig.py). It adds the `MCPServer` feature gate and an MCP server named `rhokp` to an existing `OLSConfig`. It does not install the Operator, configure a model, copy Secrets, or create NetworkPolicies.

### 5.2 An Illustrative Combined Configuration

The following shows how the model connection, default model, and MCP connection fit into one configuration. **This illustrates the structure; it is not a universal installation manifest for replacing the entire object.** Verify provider types, URLs, models, Secrets, and available fields against the installed CRD. Do not overwrite an existing configuration and lose other MCP servers, feature gates, or organizational security settings.

```yaml
# AI-Author: Codex (OpenAI model not exposed by runtime)
apiVersion: ols.openshift.io/v1alpha1
kind: OLSConfig
metadata:
  name: cluster
spec:
  featureGates:
    - MCPServer
  llm:
    providers:
      - name: approved-model-provider
        type: openai
        url: https://llm.example.com/v1
        credentialsSecretRef:
          name: llm-api-credentials
        credentialKey: apitoken
        models:
          - name: approved-tool-capable-model
  ols:
    defaultProvider: approved-model-provider
    defaultModel: approved-tool-capable-model
  mcpServers:
    - name: rhokp
      url: http://rhokp-mcp.rhokp.svc.cluster.local/mcp
      timeout: 30
      headers:
        - name: Authorization
          valueFrom:
            type: secret
            secretRef:
              name: rhokp-mcp-auth
```

`llm.providers` defines the models and their authentication; `ols.defaultProvider/defaultModel` selects the default model; `mcpServers` defines external tool endpoints. `rhokp` is the server's logical name, not a tool name. Once connected, clients can discover `rhokp_health`, `rhokp_search`, `rhokp_get_document`, `rhokp_get_cve`, and `rhokp_get_erratum`.

The MCP URL omits `:18081` because clients connect to Service port **80**, which forwards to Pod port **18081**. The authentication header's Secret key is `header` under this integration contract. Do not add a `key:` field here without confirming that the CRD supports it.

Before making changes, inspect:

```bash
oc explain olsconfig.spec.llm --recursive
oc explain olsconfig.spec.ols --recursive
oc explain olsconfig.spec.featureGates
oc explain olsconfig.spec.mcpServers --recursive
```

Follow the [integration procedure](openshift.md#optional-openshift-lightspeed-integration): generate a patch from a protected copy of the current configuration, review it, and perform a server-side dry run before applying it. The merge helper preserves other MCP servers and feature gates in its input, but arrays in a merge patch are replaced in full. If the configuration changes between patch generation and application, read it again and regenerate the patch to avoid overwriting concurrent changes.

### 5.3 Cross-Namespace NetworkPolicy Example

The default rules allow only callers in the same namespace. If Lightspeed runs in `openshift-lightspeed`, an **additional** ingress rule is required. The following is a complete example for review; the base installer does not apply it automatically. First verify that the application Pod labels actually match.

```yaml
# AI-Author: Codex (OpenAI model not exposed by runtime)
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rhokp-mcp-from-lightspeed
  namespace: rhokp
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: rhokp-mcp
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: openshift-lightspeed
          podSelector:
            matchLabels:
              app.kubernetes.io/component: application-server
              app.kubernetes.io/part-of: openshift-lightspeed
      ports:
        - protocol: TCP
          port: 18081
```

The two selectors in **the same `from` entry** are combined with AND: the caller must be both in the specified namespace and a matching application Pod. Splitting them into separate entries changes this to OR and broadens access. The port here is the destination Pod's port 18081. If the caller also has egress restrictions, check DNS and destination access; do not resolve timeouts by allowing every namespace. Allow rules from other NetworkPolicies are additive, so this example does not prove that broader access rules are absent from the cluster.

## 6. Why Might There Be Two RHoKP Installations?

| Aspect | This project's full RHoKP | Lightspeed built-in retrieval operand (where supported by the version) |
|---|---|---|
| Managed by | This project's Deployment template | Lightspeed Operator / `OLSConfig` |
| Location in this document | `rhokp` namespace | Namespace containing the Lightspeed operand |
| Solr collection | `portal` | `portal-rag` |
| Usage | MCP tools query the full knowledge content | Lightspeed built-in retrieval path |
| Meaning of counts | Complete document counts | Retrieval chunk counts; not directly comparable |
| Storage configuration entry point | This project's Deployment template | `spec.ols.deployment.rhokp.resources`, if supported by the current CRD |

Adding MCP does not replace or disable built-in retrieval. Do not simply repoint the MCP backend to `portal-rag`: its schema and purpose differ.

Changing “Lightspeed's RHoKP temporary storage to 2 GiB” affects the **Operator-managed component in the right column**, not this project's default 1 GiB temporary volume in the left column. The base installation does not perform this tuning automatically. Consider it only if the CRD supports it and measured capacity requirements justify it. Save the complete original resources configuration and preserve CPU/memory settings, then verify the generated volume and real queries. Pod Ready alone does not establish success. See [managed storage tuning](openshift.md#optional-managed-portal-storage-tuning).

## 7. What Evidence Confirms a Successful Installation?

The following are verification commands and expected results, not captured output from a live cluster. Do not use `oc get secret -o yaml` to paste credentials into tickets or chat.

```bash
# Base workloads: READY should reach 1/1 for each Deployment.
oc -n rhokp get deploy,pod,svc,endpointslice
oc -n rhokp get networkpolicy
oc -n rhokp get secret rhokp-full-registry rhokp-full-access-key rhokp-mcp-server-auth rhokp-mcp-auth
oc -n rhokp rollout status deployment/rhokp
oc -n rhokp rollout status deployment/rhokp-mcp

# With Lightspeed: verify caller labels and owner status.
oc -n openshift-lightspeed get pods --show-labels
oc get olsconfig cluster -o jsonpath='{.status.conditions}'
```

| Acceptance layer | Required evidence | What it does not establish |
|---|---|---|
| Resources | Both Deployments are available; Services have EndpointSlice backends | Content is searchable or credentials work |
| MCP path | Run `bash deploy/openshift/validate.sh rhokp` from the repository root; initialization, tool discovery, real retrieval, and rejection of invalid requests all pass | Reachability from other namespaces or actual Lightspeed tool calls |
| Lightspeed | Owner reconciliation is healthy and the configured model is usable | The model will select RHoKP tools |
| Real question and answer | An approved, non-sensitive question explicitly requests `rhokp_search`; the tool succeeds, the answer contains content, and timestamps can be correlated across logs on both sides | Correctness for every question or compatibility with every model version |

Base validation runs the client inside the MCP Pod, keeping the token in the Pod. Real Lightspeed validation also involves model costs and outbound data boundaries, so approve and execute it separately.

For common failures, check in this order: for `ImagePullBackOff`, inspect image authorization/pulls and node disk space; for a portal that is not ready, inspect the access key, index, and startup permissions; for MCP 401 responses, check that authentication matches on both sides; for Lightspeed timeouts, inspect cross-namespace policies, labels, and Service ports. If an answer appears without tool logs, investigate tool selection rather than treating the answer as proof of MCP connectivity.

## 8. Summary

The completed base installation consists of **two applications, two internal Services, their Secrets, and ingress policies in the `rhokp` namespace**. Complete Lightspeed integration additionally requires **an installed Operator, a working model configuration, an RHoKP MCP entry in OLSConfig, a caller-side authentication Secret, network access, and a verified real question-and-answer exchange using a tool**.
