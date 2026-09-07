---
name: deploy-rhokp-openshift
description: Deploy and validate the containerized Red Hat Offline Knowledge Portal MCP adapter on OpenShift, optionally integrating an installed OpenShift Lightspeed instance.
---

# Deploy RHoKP on OpenShift

AI-Author: Codex (OpenAI model not exposed by runtime)

Require a full checkout of this repository; this skill is not a standalone installer. Locate the checkout root containing `deploy/openshift/deploy.sh`, `mcp/`, and `docs/openshift.md`. Read `docs/openshift.md` before deployment and use its canonical scripts rather than copying Python source into ConfigMaps.

Confirm cluster identity, target namespace ownership, registry entitlement, approved digest-pinned portal and MCP images, protected credential-file paths, and capacity. Do not infer permission for live deployment from a documentation or diagnosis request. Inspect existing resources before applying; use the documented server dry-run and obtain any missing authorization.

Use isolated credential Secrets and preserve existing MCP tokens. Keep the Service internal unless external exposure is explicitly requested. Do not grant broad SCC permissions to make a failed image start; identify the failure first. Do not mount storage over image-seeded content without verifying the chosen image layout.

Run `deploy/openshift/validate.sh` after deployment. Separate rollout, real MCP content behavior, intended-client reachability, and Lightspeed tool-use proof in the result. Report unrun tests and unsupported release-dependent features explicitly.

For optional Lightspeed integration, read the documentation's integration section and inspect the installed CRD. Use `deploy/openshift/merge_olsconfig.py` only when that schema is supported, preserve unrelated owner fields, and never patch generated children. In cross-namespace topology, combine namespace and Pod selectors in one NetworkPolicy peer and place the header Secret where the Operator resolves it. Approve external-LLM content egress before real queries.

Retain rollback configuration and old migration endpoints until the replacement passes actual client requests. Never retire old services or delete a namespace implicitly.
