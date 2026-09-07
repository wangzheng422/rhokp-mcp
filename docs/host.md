# Linux host deployment

AI-Author: Codex (OpenAI model not exposed by runtime)

Run RHOKP and the MCP adapter as separate rootful Podman containers, managed by
systemd Quadlet. No Kubernetes cluster is required. The dedicated internal network
allows MCP to reach `http://rhokp:8080`; only loopback ports 18080 (portal) and
18081 (MCP) are published. Host root and processes with equivalent container
privileges remain trusted. This is not a boundary against a compromised host.

## Prerequisites and review

Use a Linux host with systemd, cgroup v2, Podman with Quadlet and a DNS-capable
Netavark network backend, Python 3 for smoke tests, and sufficient disk/memory for
the vendor image and its search index. `SOLR_MEM=4g` is a heap setting, not total
container memory; size the host with additional headroom. Review
[Podman's Quadlet documentation](https://docs.podman.io/en/latest/markdown/podman-systemd.unit.5.html)
for your installed version.

Run commands below from the checkout root (the directory containing `Containerfile`).
First inspect `podman version`, `sudo podman ps -a`, `sudo podman network ls`,
`sudo podman secret ls`, `systemctl status rhokp rhokp-mcp`, and
`ss -ltn`. Inspect `/etc/containers/systemd/` for existing units. Do not overwrite
existing names or occupied ports without resolving ownership. Quadlet uses
container replacement, so name collisions are particularly important.

Review [the three templates](../deploy/host/). Customize `Image=` references and
ports before installing. The pinned vendor digest is a sample snapshot reference,
not a claim that it is the latest release. Obtain the RHOKP image and access key
directly under your own Red Hat entitlement; neither is included or redistributed.
An approved internal mirror is supported by replacing `Image=`. Keep the MCP
`RHOKP_IMAGE_DIGEST` and `RHOKP_SNAPSHOT_DATE` truthful for the selected snapshot.

## Stage images and credentials

These commands change the chosen host; execute them only after deployment approval.
Authenticate interactively to the vendor registry using `sudo podman login
registry.redhat.io`, or a protected registry auth file. Never put passwords in
arguments. Pull the exact vendor image from `rhokp.container` with `sudo podman
pull IMAGE_REFERENCE`. For the MCP adapter use the [prebuilt release](../README.md#use-a-prebuilt-release): run `sudo podman pull ghcr.io/wangzheng422/rhokp-mcp:v0.1.2`. The Quadlet template uses that reference. For a downloaded archive use `sudo podman load` instead. Rootful Quadlet uses rootful image storage.

For development or before the first public release, build the adapter locally:

```bash
sudo podman build --format docker -t localhost/rhokp-mcp:0.1.2 -f Containerfile .
```

For a local build, set the MCP Quadlet `Image=` to `localhost/rhokp-mcp:0.1.2` before installing it.

For a disconnected host, stage both images using your approved image-transfer
process before startup. `Pull=never` deliberately prevents an unexpected pull.
Only the MCP image may be distributed as this project's output; vendor image
transfer remains subject to your entitlement. The internal runtime network has
no outbound routing; image pulls occur on the host, not from that network.

Provision `/etc/rhokp-secrets/access-key` containing only the vendor access key
and `/etc/rhokp-secrets/mcp-token` containing a randomly generated token of at
least 32 characters, using your secret manager. The directory must be root-owned
mode 0700 and files root-owned mode 0600. Do not place secrets in the checkout,
shell history, screenshots, or support logs. Normalize the access key before
creating its Podman secret: a terminal LF/CRLF from a secret-manager export must
not enter the vendor's `ACCESS_KEY` environment variable. The host-local helper
accepts one value with at most one line ending, rejects whitespace/control bytes,
and creates a new protected file without overwriting an existing path. If it fails,
stop and correct the input; do not continue with the original file.

```bash
sudo python3 deploy/host/normalize_access_key.py /etc/rhokp-secrets/access-key /etc/rhokp-secrets/access-key.normalized && sudo podman secret create rhokp-access-key /etc/rhokp-secrets/access-key.normalized
sudo podman secret create rhokp-mcp-token /etc/rhokp-secrets/mcp-token
```

The portal requires `ACCESS_KEY` as an environment variable; Podman supplies it
from its secret store. Privileged container inspection can still expose it. MCP
reads a mounted mode-0400 file via `MCP_TOKEN_FILE` as UID 10001. Podman's default
secret store is not a substitute for encrypted host storage or root access control.

## Install and start

After reviewing/customizing the local templates, validate generation without
starting containers (generator path can vary by distribution):

```bash
QUADLET_UNIT_DIRS="$PWD/deploy/host" /usr/lib/systemd/system-generators/podman-system-generator --dryrun
```

Then install only the named files, after confirming no existing deployment will
be overwritten:

```bash
sudo install -d -m 0755 /etc/containers/systemd
sudo install -m 0644 deploy/host/rhokp.network deploy/host/rhokp.container deploy/host/rhokp-mcp.container /etc/containers/systemd/
sudo systemctl daemon-reload
sudo systemctl start rhokp.service rhokp-mcp.service
sudo systemctl status rhokp.service rhokp-mcp.service --no-pager
```

Quadlet's `[Install]` section supplies boot activation when units are generated;
do not use `systemctl enable` on generated services. `After=` is startup ordering,
not application readiness. Portal initialization can take substantial time.

## Validate and connect

```bash
sudo podman port rhokp
sudo podman port rhokp-mcp
sudo podman network inspect rhokp-private
sudo python3 tests/smoke_mcp.py --endpoint http://127.0.0.1:18081/mcp --token-file /etc/rhokp-secrets/mcp-token
```

Require the smoke test to pass, including authentication rejection, initialization,
tool enumeration, and actual search/document retrieval. A running unit or HTTP
health endpoint alone is insufficient. If startup is incomplete, review bounded
service logs locally, redact credentials before sharing, and rerun the smoke test
after portal readiness. Confirm published addresses remain `127.0.0.1`.

Configure a compatible HTTP MCP client with endpoint
`http://127.0.0.1:18081/mcp` and `Authorization: Bearer <token>`, using its protected
credential mechanism. The placeholder is not a command to paste with a real token
into history. A client on a different host cannot access this loopback endpoint.
Use an explicitly authorized SSH tunnel or a TLS-authenticated reverse proxy;
do not casually change the bind to `0.0.0.0`. For remote readers set
`RHOKP_SOURCE_BASE_URL` to their approved, reachable portal URL, otherwise returned
source links point to the reader's own loopback interface. A containerized client
also has its own loopback namespace.

## Updates, rollback, and shutdown

Record installed image references and preserve old images before updating. Stage
the replacement image, edit the relevant installed `Image=` and snapshot metadata,
run `daemon-reload`, then restart the changed service and rerun the smoke test.
For a portal update stop MCP first, restart RHOKP, start MCP and validate readiness.
Rollback restores the recorded references and repeats the same validation; do not
delete the prior images until acceptance. Container writable state is disposable;
this deployment uses the vendor snapshot rather than promising persistence for
unmodeled vendor runtime changes.

For secret rotation, normalize vendor keys again to a new protected output path
using the helper above, then provision a new named Podman secret from that file,
update `Secret=`, reload and restart the consuming service (recreating its
container), then validate before retiring the old secret. Update MCP clients when
rotating the bearer token. Merely editing the source file does not rotate the
already-created Podman secret.

```bash
sudo systemctl stop rhokp-mcp.service rhokp.service
```

Stopping retains images, secret objects and source credential files. To keep it
stopped after reboot, remove `WantedBy=multi-user.target` from the two installed
container files and reload systemd. Removal of units, networks, images or secrets
is a separate cleanup decision requiring explicit target review; do not use broad
Podman prune commands.
