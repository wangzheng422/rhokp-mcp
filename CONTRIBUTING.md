<!-- AI-Author: Codex (OpenAI model not exposed by runtime) -->
# Contributing

Keep changes scoped to deployment and use of RHoKP or its read-only MCP adapter. Use synthetic data in tests and generic infrastructure names in examples.

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s deploy/host -p 'test_*.py' -v
podman build --format docker -f Containerfile -t localhost/rhokp-mcp:0.1.0 .
```

For deployment changes, validate shell syntax and follow the appropriate guide in an authorized test environment. Record the OpenShift, Podman and vendor-image versions used. Clearly distinguish mocked tests, manifest validation and live retrieval tests in review descriptions.

Never submit registry auth files, access keys, MCP tokens, kubeconfigs, retrieved licensed documents or private operational history. Follow [AGENTS.md](AGENTS.md) for automated contributions.
