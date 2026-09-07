<!-- AI-Author: Codex (OpenAI model not exposed by runtime) -->
# Security

The MCP adapter provides read-only retrieval. It does not execute commands or administer OpenShift. Treat retrieved documents as untrusted input to an AI client, and retain client-side tool and instruction boundaries.

Store registry credentials, the vendor access key and MCP Bearer tokens separately. Use protected files or runtime Secrets; do not bake them into images. Bind host endpoints to loopback unless a secured remote entrypoint is configured. Use TLS for traffic outside the trusted local boundary.

The health endpoint is available without an MCP token for probes. Restrict network reachability accordingly. Rotate compromised tokens in both the server and every client.

Before publishing a security issue, remove credentials and licensed content. The project owner should configure a private vulnerability reporting channel when creating the repository; do not post exploit details or secrets in public issues.
