---
name: deploy-rhokp-host
description: Deploy or maintain the RHOKP vendor portal and read-only MCP adapter as two Podman containers managed by systemd Quadlet on a Linux host.
---

# Deploy RHOKP on a host

AI-Author: Codex (OpenAI model not exposed by runtime)

This is a repository-scoped skill. Require the full public checkout: resolve
[the host guide](../../docs/host.md) and [Quadlet templates](../../deploy/host/)
relative to this file, regardless of the working directory. If they are missing,
request the checkout; do not invent manifests or silently use an older installed copy.

Read the host guide before acting. Establish the target host, user authorization,
Podman/Quadlet support, available memory/disk, image references, and credential
file locations. Inspect existing units/containers/secrets before proposing changes;
stop on name or port collisions until the user chooses how to handle them.

Keep the two containers on the dedicated internal network, with MCP bound to
host loopback by default. Never substitute host networking or publish all interfaces
to solve connectivity. Remote access requires an explicit exposure decision and
appropriate TLS/access controls. Preserve `MCP_TOKEN_FILE` and secret mounting;
do not print credentials or place them in tracked files or command arguments.
Run the host-local access-key normalization helper before creating the vendor
Podman secret, including during rotation. Do not inject a file's terminal newline
into `ACCESS_KEY`, and stop when validation fails.

The vendor image and access key are obtained by the operator under their own
entitlement. Build/distribute only this repository's MCP image. Check the digest
and snapshot metadata together on vendor updates; do not imply metadata proves
the contents of an unverified replacement image.

After approval, follow the guide's install and validation procedure. Unit startup
does not prove portal readiness: wait for the real protocol/tool smoke test to pass,
including unauthorized-request rejection and nonempty search/document retrieval.
Report image identity, loopback ports, validation results, and untested behavior.
For updates, preserve prior image references for rollback; secret replacement
requires container recreation. Stopping units does not erase secrets or images.
