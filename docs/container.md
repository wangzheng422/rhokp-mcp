# MCP container

AI-Author: Codex (OpenAI model not exposed by runtime)

The image contains only the Python standard-library adapter, not the Red Hat
Offline Knowledge Portal content image. Configure an existing reachable portal
as `RHOKP_BASE_URL`. Entitlement, content acquisition, and redistribution rights
remain separate prerequisites.

## Use the published image

Pull `ghcr.io/wangzheng422/rhokp-mcp:v0.1.3`. Alternatively download `rhokp-mcp-v0.1.3-linux-amd64.tar.gz` and `SHA256SUMS` from [Releases](https://github.com/wangzheng422/rhokp-mcp/releases), check the checksum, decompress, and load with Podman. See [the README](../README.md#use-a-prebuilt-release) for commands. GitHub Actions produces the downloads; wait for a successful release workflow before downloading newly published versions.

In the runtime example below, replace `localhost/rhokp-mcp:0.1.3` with your pulled release reference when using a prebuilt image.

## Build locally for development

From the repository root:

```bash
podman build --format docker -t localhost/rhokp-mcp:0.1.3 -f Containerfile .
python3 -m unittest discover -s tests -v
```

To transfer a built image without a registry, use `podman save --format docker-archive -o rhokp-mcp.tar localhost/rhokp-mcp:0.1.3` and `podman load -i rhokp-mcp.tar` on the destination. For the rootful host deployment, load with `sudo podman load` into the same rootful image store used by Quadlet. Keep image archives outside the source repository.

The default base is `docker.io/library/python:3.12-slim`. For reproducible or
disconnected builds, mirror an approved base and supply its immutable digest:
`--build-arg BASE_IMAGE=registry.example.com/team/python@sha256:<approved-digest>`.
Use `--format docker` to retain HEALTHCHECK metadata (Podman's OCI format omits
it). No pip packages are downloaded. The allowlists `.containerignore` and `.dockerignore` exclude
credentials, documentation, tests, and unrelated files from the image context.

Create a runtime-only token without printing it or placing it in shell arguments:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(48))' | podman secret create rhokp-mcp-token -
podman run -d --name rhokp-mcp --read-only --cap-drop=ALL \
  --security-opt=no-new-privileges --user 10001:0 \
  --secret rhokp-mcp-token,target=mcp_token,uid=10001,gid=0,mode=0400 \
  -e RHOKP_BASE_URL=http://portal.example.com:8080 \
  -p 127.0.0.1:18081:18081 localhost/rhokp-mcp:0.1.3
```

Replace the portal example with your internal service address. The process
defaults to UID 10001, but requires no specific UID, home directory, writable
application directory, or privileged port. For a different UID, make the mounted
token readable by that UID (or an assigned group); do not make it world-readable.
OpenShift Secret volumes provide the equivalent token file. The token must have
at least 32 characters and no internal whitespace. It is read only at startup;
restart after rotation. Never put tokens in a Containerfile, image layer, Git,
command-line option, or literal environment variable.

The MCP endpoint is `/mcp` on port 18081 and requires `Authorization: Bearer`.
Supply `MCP_ALLOWED_ORIGINS` as a comma-separated exact allowlist only when a
browser client sends Origin. Origin-less authenticated clients are supported.
Terminate TLS at a trusted ingress and restrict network access; the application
itself serves HTTP. `RHOKP_TLS_VERIFY` defaults to true for HTTPS backend access;
prefer installing a trusted CA over disabling verification.

`GET /healthz` is unauthenticated backend readiness, not process-only liveness;
it exposes bounded snapshot metadata and document count. Restrict it to the
cluster or monitoring network if this metadata is sensitive. The image health
check calls it every 30 seconds. A backend outage makes the image unhealthy;
orchestrators should use a TCP process-liveness probe separately to avoid restart
loops. Overriding the listen port also requires updating the image health check.

Tests use synthetic data and a loopback fake Solr backend. They verify input
validation, read-only tool definitions, HTTP auth and Origin rejection,
initialization, discovery, notifications, token validation, and health tool
dispatch. They do not prove compatibility with every MCP client, validate a
licensed content snapshot, or replace deployment security review.
