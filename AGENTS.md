<!-- AI-Author: Codex (OpenAI model not exposed by runtime) -->
# Working in this repository

This project deploys Red Hat Offline Knowledge Portal and a read-only MCP adapter. Select the user's runtime first: `deploy/host/` for Podman/Quadlet; `deploy/openshift/` for cluster Deployments. Read the matching guide and Skill before deployment.

- Keep `mcp/rhokp_mcp_server.py` the canonical implementation. Both runtimes use the same built MCP image.
- Keep each deployment independently usable. Do not replace OpenShift Pod selectors with host IP endpoints.
- Obtain credentials at runtime through protected files, secrets, or stdin. Never embed credentials or licensed knowledge in source, logs, images or examples.
- Preserve read-only tool semantics, bounded responses, Bearer authentication, Origin validation and constrained document paths.
- Inspect actual installed OpenShift CRDs before changing Lightspeed configuration. Update the owner CR rather than operator-generated resources.
- Use configurable image references. Validate the selected vendor snapshot and use digests for repeatable deployments.
- Run `python3 -m unittest discover -s tests -v` after adapter changes. Validate changed shell files with `bash -n`, build the image after packaging changes, and distinguish fixture tests from live backend validation.
- Read `docs/releasing.md` before publishing. Public examples must not contain private infrastructure identities or operational records.
- Record AI contributions in native comments using the runtime-exposed model identity, or `model not exposed by runtime` when unavailable; preserve prior attribution.

Available workflows: [host Skill](skills/deploy-rhokp-host/SKILL.md), [OpenShift Skill](skills/deploy-rhokp-openshift/SKILL.md).
