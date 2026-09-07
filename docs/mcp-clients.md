<!-- AI-Author: Codex (OpenAI model not exposed by runtime) -->
# Using the MCP endpoint

Use an HTTP MCP client with support for JSON responses. Configure the endpoint supplied by your deployment and an Authorization header sourced from the client's secret store:

```text
URL: http://127.0.0.1:18081/mcp
Authorization: Bearer <runtime-secret>
```

For OpenShift, use the cluster Service URL from a client with cluster network access. To use a workstation client, establish a local port-forward or configure an authenticated TLS entrypoint. Do not publish the internal plain-HTTP URL to untrusted networks.

The adapter supports the 2025-03-26, 2025-06-18 and 2025-11-25 protocol versions. The normal protocol sequence is `initialize`, `notifications/initialized`, `tools/list`, then `tools/call`. The adapter is stateless and returns JSON; it is not an SSE subscription server. See the [2025-11-25 transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) for that protocol contract. Newer protocol revisions require separate compatibility work. Use the bundled smoke client against the licensed backend:

```bash
python3 tests/smoke_mcp.py --endpoint http://127.0.0.1:18081/mcp --token-file /secure/path/mcp-token
```

Example agent request: “Search the offline knowledge portal for troubleshooting a failing OpenShift operator. Read the relevant solution and cite its source.” Verify a successful `rhokp_search` call and use `rhokp_get_document` on a returned `source_path`. Source URLs may require network connectivity even though document retrieval was offline; retain the source path and snapshot identity in citations.

`rhokp_get_cve` accepts a CVE identifier; `rhokp_get_erratum` accepts an RHSA, RHBA or RHEA identifier. Content availability depends on the selected snapshot. Health readiness alone does not prove every content category is present.
