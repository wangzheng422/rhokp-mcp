<!-- AI-Author: Codex (OpenAI model not exposed by runtime) -->
# Publishing the repository and MCP image

Original adapter and deployment code are licensed under [Apache-2.0](../LICENSE). No license for Red Hat software, vendor images or knowledge content is granted by this project.

Create a new repository from this directory's files, with a new Git history. Do not copy a development repository's `.git`, private records, credentials or old deployment archives. A `.gitignore` does not remove secrets from existing Git history.

## Automated release

The [GitHub Actions workflow](../.github/workflows/release.yml) runs when a GitHub Release is published. It checks that the repository is public, validates the version tag, runs the standard-library test suites, builds a linux/amd64 MCP image, and publishes:

| Destination | Artifact |
|---|---|
| GHCR | `ghcr.io/wangzheng422/rhokp-mcp:vMAJOR.MINOR.PATCH` |
| GitHub Release | `rhokp-mcp-vMAJOR.MINOR.PATCH-linux-amd64.tar.gz` |
| GitHub Release | `SHA256SUMS` |
| GitHub Release | `rhokp-mcp-vMAJOR.MINOR.PATCH-source.tar.gz` including deployment guides and Skills |

The archive contains the same tagged image for `podman load` or `docker load`. No vendor portal image or knowledge is included. A release tag is required; no mutable `latest` alias is published.

Before the first release:

1. Include the hidden `.github/` directory and the Apache-2.0 license in the repository root.
2. Enable GitHub Actions and allow the workflow token to write repository contents and packages according to organization policy.
3. Make the repository public, then publish a GitHub Release with a tag such as `v0.1.0`, including the workflow in that tagged commit. Creating a tag alone does not trigger this workflow.
4. Wait for the workflow to succeed. Confirm both Release assets and the versioned GHCR image exist.
5. Review the GHCR package visibility and set it public if needed, then verify an unauthenticated pull. A public source repository does not by itself prove its container package is publicly readable.

The workflow uses the automatically supplied `GITHUB_TOKEN`; a personal access token is not required by this implementation. It skips a private repository deliberately, so making the repository public later does not retroactively process old release events. Publish a new version after migration. Test artifact availability before advertising a release as ready.

Existing archive/checksum assets cause the workflow to stop before pushing an image; it never overwrites those assets. Publishing to GHCR and uploading Release assets are separate operations, so a failed upload can leave a published image. Review that state before retrying; a retry before assets exist may rebuild and replace the version tag. Prefer a new version for a changed build and deploy by digest. SemVer prerelease tags are accepted; `+build` metadata is not supported in image tags.

The build runs on GitHub's hosted runner and requires access to the base-image registry. The workflow currently targets linux/amd64 only. Consult [GitHub's publishing guide](https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images) and [Container registry guide](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) for organization policy and visibility settings.

## Manual developer builds

For development or an independently managed registry:

```bash
MCP_IMAGE=registry.example.com/team/rhokp-mcp:0.1.0
podman build --format docker -f Containerfile -t "$MCP_IMAGE" .
podman login registry.example.com
podman push "$MCP_IMAGE"
```

Use the registry's returned digest in deployments. Publish only the adapter image built by `Containerfile`; obtain and mirror the RHoKP vendor image separately under your entitlement. Build on each supported architecture before claiming multi-architecture support.

Replace the example registry with your actual destination. Record tested versions and image digests in the release description. New Release downloads are usable only after their workflow succeeds.
