#!/usr/bin/env python3
# AI-Author: Codex (OpenAI gpt-5.6-sol)
# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Create a minimal merge patch that adds or replaces only the RHoKP MCP entry."""

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--secret-name", default="rhokp-mcp-auth")
    args = parser.parse_args()
    current = json.load(sys.stdin)
    spec = current.get("spec")
    if not isinstance(spec, dict):
        raise SystemExit("OLSConfig has no object spec")
    gates = spec.get("featureGates") or []
    if not isinstance(gates, list) or not all(isinstance(item, str) for item in gates):
        raise SystemExit("OLSConfig spec.featureGates is not a string array")
    if "MCPServer" not in gates:
        gates.append("MCPServer")
    servers = spec.get("mcpServers") or []
    if not isinstance(servers, list) or not all(isinstance(item, dict) for item in servers):
        raise SystemExit("OLSConfig spec.mcpServers is not an object array")
    servers = [item for item in servers if item.get("name") != "rhokp"]
    servers.append(
        {
            "name": "rhokp",
            "url": f"http://rhokp-mcp.{args.namespace}.svc.cluster.local/mcp",
            "timeout": 30,
            "headers": [
                {
                    "name": "Authorization",
                    "valueFrom": {
                        "type": "secret",
                        "secretRef": {"name": args.secret_name},
                    },
                }
            ],
        }
    )
    json.dump({"spec": {"featureGates": gates, "mcpServers": servers}}, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
