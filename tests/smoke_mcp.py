#!/usr/bin/python3
# AI-Author: Codex (OpenAI gpt-5.6-sol)
# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Protocol and tool smoke test for the deployed RHoKP MCP server."""

import argparse
import json
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple


def request(
    endpoint: str,
    token: Optional[str],
    payload: Optional[Dict[str, Any]] = None,
    method: str = "POST",
    origin: Optional[str] = None,
) -> Tuple[int, Optional[Dict[str, Any]]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json, text/event-stream"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body.decode("utf-8")) if body else None
    except urllib.error.HTTPError as exc:
        body = exc.read()
        return exc.code, json.loads(body.decode("utf-8")) if body else None


def rpc(endpoint: str, token: str, request_id: int, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    status, body = request(
        endpoint,
        token,
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
    )
    assert status == 200, (method, status, body)
    assert isinstance(body, dict) and body.get("id") == request_id, (method, body)
    assert "error" not in body, (method, body)
    return body["result"]


def tool_call(endpoint: str, token: str, request_id: int, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    return rpc(endpoint, token, request_id, "tools/call", {"name": name, "arguments": arguments})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", default="http://127.0.0.1:18081/mcp")
    parser.add_argument("--token-file", default="/etc/rhokp-mcp/token")
    args = parser.parse_args()
    with open(args.token_file, "r", encoding="utf-8") as stream:
        token = stream.read().strip()
    assert len(token) >= 32

    status, _ = request(
        args.endpoint,
        None,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert status == 401, status
    print("unauthorized_status=401")

    status, _ = request(
        args.endpoint,
        token,
        {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {}},
        origin="https://attacker.invalid",
    )
    assert status == 403, status
    print("invalid_origin_status=403")

    initialized = rpc(
        args.endpoint,
        token,
        10,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "rhokp-smoke", "version": "0.1.0"},
        },
    )
    assert initialized["protocolVersion"] == "2025-11-25"
    assert initialized["capabilities"]["tools"]["listChanged"] is False
    print("initialize=PASS protocol=2025-11-25")

    status, body = request(
        args.endpoint,
        token,
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    )
    assert status == 202 and body is None, (status, body)
    print("initialized_notification=PASS status=202")

    listed = rpc(args.endpoint, token, 11, "tools/list", {})
    names = [tool["name"] for tool in listed["tools"]]
    expected = {
        "rhokp_health",
        "rhokp_search",
        "rhokp_get_document",
        "rhokp_get_cve",
        "rhokp_get_erratum",
    }
    assert set(names) == expected
    assert all(tool["annotations"]["readOnlyHint"] for tool in listed["tools"])
    print("tools_list=PASS count={}".format(len(names)))

    health = tool_call(args.endpoint, token, 12, "rhokp_health", {})
    assert health["isError"] is False
    health_data = health["structuredContent"]
    assert health_data["status"] == "ok" and health_data["documents"] > 0
    print(
        "health=PASS documents={} snapshot_date={} digest_present={}".format(
            health_data["documents"],
            health_data["snapshot_date"],
            bool(health_data["image_digest"]),
        )
    )

    search = tool_call(
        args.endpoint,
        token,
        13,
        "rhokp_search",
        {"query": "OpenShift", "content_type": "solution", "limit": 2},
    )
    assert search["isError"] is False
    search_data = search["structuredContent"]
    assert search_data["total"] > 0 and search_data["returned"] == 2
    assert all(item["source_path"].startswith("/solutions/") for item in search_data["results"])
    print(
        "search_solution=PASS total={} returned={} snippets={}".format(
            search_data["total"],
            search_data["returned"],
            sum(len(item["snippets"]) for item in search_data["results"]),
        )
    )

    source_path = search_data["results"][0]["source_path"]
    document = tool_call(
        args.endpoint,
        token,
        14,
        "rhokp_get_document",
        {"identifier": source_path, "max_chars": 1200},
    )
    assert document["isError"] is False
    document_data = document["structuredContent"]
    assert document_data["content"] and document_data["source_path"].startswith("/solutions/")
    print(
        "get_document=PASS returned_chars={} truncated={}".format(
            document_data["returned_chars"], document_data["truncated"]
        )
    )

    cve_search = tool_call(
        args.endpoint,
        token,
        15,
        "rhokp_search",
        {"query": "OpenShift", "content_type": "cve", "limit": 1},
    )["structuredContent"]
    cve_id = next(
        part
        for part in cve_search["results"][0]["source_path"].split("/")
        if part.startswith("CVE-")
    )
    cve = tool_call(args.endpoint, token, 16, "rhokp_get_cve", {"cve_id": cve_id, "max_chars": 1000})
    assert cve["isError"] is False and cve["structuredContent"]["content"]
    print("get_cve=PASS id_shape_valid={}".format(cve_id.startswith("CVE-")))

    errata_search = tool_call(
        args.endpoint,
        token,
        17,
        "rhokp_search",
        {"query": "OpenShift", "content_type": "errata", "limit": 1},
    )["structuredContent"]
    advisory_id = errata_search["results"][0]["id"]
    erratum = tool_call(
        args.endpoint,
        token,
        18,
        "rhokp_get_erratum",
        {"advisory_id": advisory_id, "max_chars": 1000},
    )
    assert erratum["isError"] is False and erratum["structuredContent"]["content"]
    print("get_erratum=PASS id_shape_valid={}".format(advisory_id.startswith("RH")))

    unsafe = tool_call(
        args.endpoint,
        token,
        19,
        "rhokp_get_document",
        {"identifier": "https://attacker.invalid/secret"},
    )
    assert unsafe["isError"] is True
    print("unsafe_url_rejected=PASS")

    injection = tool_call(
        args.endpoint,
        token,
        20,
        "rhokp_search",
        {"query": "{!lucene}*:*"},
    )
    assert injection["isError"] is True
    print("solr_local_parameter_rejected=PASS")

    status, _ = request(args.endpoint, token, None, method="GET")
    assert status == 405
    print("mcp_get_status=405")
    print("all_tests=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
