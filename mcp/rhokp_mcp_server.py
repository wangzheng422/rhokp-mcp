#!/usr/bin/python3
# AI-Author: Codex (OpenAI model not exposed by runtime)
# AI-Author: Codex (OpenAI gpt-5.6-sol)
"""Read-only Streamable HTTP MCP adapter for Red Hat Offline Knowledge Portal."""

import argparse
import hmac
import html
import json
import logging
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SERVER_NAME = "rhokp-mcp"
SERVER_VERSION = "0.1.2"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
MAX_REQUEST_BYTES = 1024 * 1024
MAX_BACKEND_BYTES = 2 * 1024 * 1024
MAX_QUERY_LENGTH = 500
MAX_DOCUMENT_CHARS = 20000
CONTENT_TYPES = {
    "solution": "solution",
    "article": "article",
    "documentation": "documentation",
    "cve": "Cve",
    "errata": "Errata",
}
ALLOWED_PATH_PREFIXES = ("/solutions/", "/articles/", "/documentation/", "/security/")
ERRATUM_RE = re.compile(r"^RH(?:SA|BA|EA)-[0-9]{4}:[0-9]+$")
CVE_RE = re.compile(r"^CVE-[0-9]{4}-[0-9]{4,}$")
SAFE_PATH_RE = re.compile(r"^/[A-Za-z0-9._~/%:-]+$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
LUCENE_SPECIAL_RE = re.compile(r"([+\-&|!(){}\[\]^\"~*?:\\/])")


class BackendError(RuntimeError):
    """Raised for a failed or invalid RHoKP backend response."""


class InputError(ValueError):
    """Raised for invalid MCP tool input."""


class _ConstrainedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects outside the configured backend before any connection."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def validate_url(self, url: str) -> None:
        if not (url == self.base_url or url.startswith(self.base_url + "/")):
            raise BackendError("RHoKP redirect left the configured origin")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validate_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    SKIP_TAGS = {"script", "style", "svg", "noscript", "template"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: List[str] = []
        self.title_parts: List[str] = []
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if not self._skip_depth and tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if not self._skip_depth and tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.parts.append(data)

    def result(self) -> Tuple[str, str]:
        title = " ".join(" ".join(self.title_parts).split())
        joined = html.unescape("".join(self.parts)).replace("\r", "")
        lines = [" ".join(line.split()) for line in joined.split("\n")]
        text = "\n".join(line for line in lines if line)
        return title, text


def _scalar(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _strip_html(value: str) -> str:
    extractor = _TextExtractor()
    extractor.feed(value)
    _, text = extractor.result()
    return text


def _escape_lucene(value: str) -> str:
    return LUCENE_SPECIAL_RE.sub(r"\\\1", value)


def _normalize_query(value: Any) -> str:
    if not isinstance(value, str):
        raise InputError("query must be a string")
    value = " ".join(value.split())
    if not value:
        raise InputError("query must not be empty")
    if len(value) > MAX_QUERY_LENGTH:
        raise InputError("query is too long")
    if CONTROL_RE.search(value) or "{!" in value:
        raise InputError("query contains unsupported control or local-parameter syntax")
    return value


def _bounded_int(value: Any, name: str, minimum: int, maximum: int, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise InputError("{} must be an integer".format(name))
    if value < minimum or value > maximum:
        raise InputError("{} must be between {} and {}".format(name, minimum, maximum))
    return value


class RhokpClient:
    def __init__(self, base_url: str, source_base_url: str, image_digest: str, snapshot_date: str) -> None:
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("RHOKP_BASE_URL must be an absolute HTTP(S) URL")
        self.base_url = base_url.rstrip("/")
        self.source_base_url = source_base_url.rstrip("/") if source_base_url else ""
        self.image_digest = image_digest
        self.snapshot_date = snapshot_date
        context = ssl.create_default_context()
        if os.environ.get("RHOKP_TLS_VERIFY", "true").lower() == "false":
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        self._redirect_handler = _ConstrainedRedirectHandler(self.base_url)
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context), self._redirect_handler)

    def _read(self, request: urllib.request.Request, timeout: float = 20.0) -> Tuple[bytes, str, Mapping[str, str]]:
        try:
            self._redirect_handler.validate_url(request.full_url)
            with self._opener.open(request, timeout=timeout) as response:
                final_url = response.geturl()
                self._redirect_handler.validate_url(final_url)
                body = response.read(MAX_BACKEND_BYTES + 1)
                if len(body) > MAX_BACKEND_BYTES:
                    raise BackendError("RHoKP response exceeded the configured size limit")
                return body, final_url, dict(response.headers.items())
        except urllib.error.HTTPError as exc:
            raise BackendError("RHoKP returned HTTP {}".format(exc.code)) from exc
        except urllib.error.URLError as exc:
            raise BackendError("RHoKP is unavailable") from exc

    def _solr(self, params: Sequence[Tuple[str, str]]) -> Dict[str, Any]:
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(
            self.base_url + "/solr/portal/select?" + query,
            headers={"Accept": "application/json", "User-Agent": SERVER_NAME + "/" + SERVER_VERSION},
        )
        body, _, _ = self._read(request)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BackendError("RHoKP returned invalid JSON") from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("response"), dict):
            raise BackendError("RHoKP returned an unexpected search schema")
        return parsed

    def health(self) -> Dict[str, Any]:
        started = time.monotonic()
        data = self._solr(
            [
                ("q", "*:*"),
                ("rows", "0"),
                ("wt", "json"),
                ("facet", "true"),
                ("facet.field", "documentKind"),
            ]
        )
        return {
            "status": "ok",
            "backend": "rhokp",
            "documents": int(data["response"].get("numFound", 0)),
            "query_time_ms": int(data.get("responseHeader", {}).get("QTime", 0)),
            "round_trip_ms": int((time.monotonic() - started) * 1000),
            "snapshot_date": self.snapshot_date or None,
            "image_digest": self.image_digest or None,
            "adapter_version": SERVER_VERSION,
        }

    def search(
        self,
        query: Any,
        content_type: Any = None,
        product: Any = None,
        limit: Any = None,
        offset: Any = None,
    ) -> Dict[str, Any]:
        normalized = _normalize_query(query)
        rows = _bounded_int(limit, "limit", 1, 10, 5)
        start = _bounded_int(offset, "offset", 0, 10000, 0)
        params: List[Tuple[str, str]] = [
            ("q", _escape_lucene(normalized)),
            ("defType", "edismax"),
            ("qf", "title^5 main_content resourceName^2 product^2"),
            ("fl", "id,title,documentKind,product,lastModifiedDate,resourceName,score"),
            ("rows", str(rows)),
            ("start", str(start)),
            ("wt", "json"),
            ("hl", "true"),
            ("hl.fl", "main_content,title"),
            ("hl.fragsize", "300"),
            ("hl.snippets", "2"),
            ("facet", "true"),
            ("facet.field", "documentKind"),
        ]
        normalized_type: Optional[str] = None
        if content_type is not None:
            if not isinstance(content_type, str) or content_type.lower() not in CONTENT_TYPES:
                raise InputError("content_type must be one of {}".format(", ".join(sorted(CONTENT_TYPES))))
            normalized_type = content_type.lower()
            params.append(("fq", "documentKind:" + CONTENT_TYPES[normalized_type]))
        if product is not None:
            if not isinstance(product, str):
                raise InputError("product must be a string")
            product = " ".join(product.split())
            if not product or len(product) > 200 or CONTROL_RE.search(product) or "{!" in product:
                raise InputError("product is invalid")
            params.append(("fq", 'product:"{}"'.format(_escape_lucene(product))))

        data = self._solr(params)
        response = data["response"]
        highlighting = data.get("highlighting", {})
        results: List[Dict[str, Any]] = []
        for document in response.get("docs", []):
            if not isinstance(document, dict):
                continue
            identifier = str(_scalar(document.get("id")) or "")
            snippets: List[str] = []
            highlighted = highlighting.get(identifier, {}) if isinstance(highlighting, dict) else {}
            if isinstance(highlighted, dict):
                for fragment in highlighted.get("main_content", [])[:2]:
                    if isinstance(fragment, str):
                        clean = _strip_html(fragment)
                        if clean:
                            snippets.append(clean[:600])
            result = {
                "id": identifier,
                "title": str(_scalar(document.get("title")) or _scalar(document.get("resourceName")) or "Untitled"),
                "content_type": str(_scalar(document.get("documentKind")) or ""),
                "product": document.get("product") or [],
                "last_modified": _scalar(document.get("lastModifiedDate")),
                "score": document.get("score"),
                "snippets": snippets,
                "source_path": self._source_path(identifier, str(_scalar(document.get("documentKind")) or "")),
            }
            result["source_url"] = self._source_url(result["source_path"])
            results.append(result)

        raw_facets = data.get("facet_counts", {}).get("facet_fields", {}).get("documentKind", [])
        facets = []
        if isinstance(raw_facets, list):
            for index in range(0, len(raw_facets) - 1, 2):
                facets.append({"value": raw_facets[index], "count": raw_facets[index + 1]})
        return {
            "query": normalized,
            "content_type": normalized_type,
            "product": product,
            "total": int(response.get("numFound", 0)),
            "offset": int(response.get("start", start)),
            "returned": len(results),
            "results": results,
            "facets": {"content_type": facets},
            "snapshot_date": self.snapshot_date or None,
            "image_digest": self.image_digest or None,
        }

    def _source_path(self, identifier: str, document_kind: str) -> str:
        if identifier.startswith("/"):
            return identifier
        if document_kind.lower() == "errata" and ERRATUM_RE.fullmatch(identifier):
            return "/errata/" + identifier
        return ""

    def _source_url(self, path: str) -> str:
        return self.source_base_url + path if self.source_base_url and path else path

    def get_document(self, identifier: Any, max_chars: Any = None) -> Dict[str, Any]:
        if not isinstance(identifier, str):
            raise InputError("identifier must be a string")
        identifier = identifier.strip()
        if ERRATUM_RE.fullmatch(identifier):
            path = "/errata/" + identifier
        elif identifier.startswith(ALLOWED_PATH_PREFIXES):
            path = identifier
        else:
            raise InputError("identifier must be a search-result path or a valid Red Hat erratum ID")
        if not SAFE_PATH_RE.fullmatch(path) or ".." in path:
            raise InputError("identifier contains an unsafe path")
        limit = _bounded_int(max_chars, "max_chars", 500, MAX_DOCUMENT_CHARS, 8000)
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "text/html", "User-Agent": SERVER_NAME + "/" + SERVER_VERSION},
        )
        body, final_url, headers = self._read(request)
        charset = "utf-8"
        content_type = headers.get("Content-Type", "")
        match = re.search(r"charset=([^; ]+)", content_type, re.I)
        if match:
            charset = match.group(1)
        try:
            page = body.decode(charset, errors="replace")
        except LookupError:
            page = body.decode("utf-8", errors="replace")
        extractor = _TextExtractor()
        extractor.feed(page)
        title, text = extractor.result()
        truncated = len(text) > limit
        return {
            "id": identifier,
            "title": title,
            "content": text[:limit],
            "truncated": truncated,
            "content_chars": len(text),
            "returned_chars": min(len(text), limit),
            "source_path": urllib.parse.urlsplit(final_url).path,
            "source_url": self._source_url(urllib.parse.urlsplit(final_url).path),
            "snapshot_date": self.snapshot_date or None,
            "image_digest": self.image_digest or None,
        }

    def get_cve(self, cve_id: Any, max_chars: Any = None) -> Dict[str, Any]:
        if not isinstance(cve_id, str) or not CVE_RE.fullmatch(cve_id.upper()):
            raise InputError("cve_id must match CVE-YYYY-NNNN")
        return self.get_document("/security/cve/" + cve_id.upper(), max_chars)

    def get_erratum(self, advisory_id: Any, max_chars: Any = None) -> Dict[str, Any]:
        if not isinstance(advisory_id, str) or not ERRATUM_RE.fullmatch(advisory_id.upper()):
            raise InputError("advisory_id must match RHSA/RHBA/RHEA-YYYY:NNNN")
        return self.get_document(advisory_id.upper(), max_chars)


def tool_definitions() -> List[Dict[str, Any]]:
    read_only = {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    }
    return [
        {
            "name": "rhokp_health",
            "description": "Check the local Red Hat Offline Knowledge Portal snapshot, index size, and adapter health.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
            "annotations": read_only,
        },
        {
            "name": "rhokp_search",
            "description": "Search licensed, internal Red Hat offline documentation, solutions, articles, CVEs, and errata. Use this before rhokp_get_document and cite source_path/source_url from the results.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1, "maxLength": MAX_QUERY_LENGTH},
                    "content_type": {"type": "string", "enum": sorted(CONTENT_TYPES)},
                    "product": {"type": "string", "minLength": 1, "maxLength": 200},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
                    "offset": {"type": "integer", "minimum": 0, "maximum": 10000, "default": 0},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            "annotations": read_only,
        },
        {
            "name": "rhokp_get_document",
            "description": "Read a bounded text extract from a source_path or erratum ID returned by rhokp_search. Arbitrary URLs and paths are rejected.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "identifier": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": MAX_DOCUMENT_CHARS, "default": 8000},
                },
                "required": ["identifier"],
                "additionalProperties": False,
            },
            "annotations": read_only,
        },
        {
            "name": "rhokp_get_cve",
            "description": "Read a bounded Red Hat CVE record from the offline snapshot by CVE ID.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "cve_id": {"type": "string", "pattern": "^CVE-[0-9]{4}-[0-9]{4,}$"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": MAX_DOCUMENT_CHARS, "default": 8000},
                },
                "required": ["cve_id"],
                "additionalProperties": False,
            },
            "annotations": read_only,
        },
        {
            "name": "rhokp_get_erratum",
            "description": "Read a bounded Red Hat security, bug-fix, or enhancement advisory from the offline snapshot.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "advisory_id": {"type": "string", "pattern": "^RH(SA|BA|EA)-[0-9]{4}:[0-9]+$"},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": MAX_DOCUMENT_CHARS, "default": 8000},
                },
                "required": ["advisory_id"],
                "additionalProperties": False,
            },
            "annotations": read_only,
        },
    ]


class McpApplication:
    def __init__(self, client: RhokpClient) -> None:
        self.client = client

    def handle(self, message: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params", {})
        if not isinstance(method, str) or not isinstance(params, dict):
            return self._error(request_id, -32600, "Invalid Request")
        if request_id is None and method.startswith("notifications/"):
            return None
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                protocol = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
                return self._result(
                    request_id,
                    {
                        "protocolVersion": protocol,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                        "instructions": "Use rhokp_search first, then retrieve only the required cited source. This server is read-only and contains an offline snapshot.",
                    },
                )
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": tool_definitions()})
            if method == "tools/call":
                return self._result(request_id, self._call_tool(params))
            return self._error(request_id, -32601, "Method not found")
        except InputError as exc:
            return self._error(request_id, -32602, str(exc))
        except Exception:
            logging.exception("MCP method failed: %s", method)
            return self._error(request_id, -32603, "Internal error")

    def _call_tool(self, params: Mapping[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise InputError("tools/call requires a tool name and object arguments")
        allowed_arguments = {
            "rhokp_health": set(),
            "rhokp_search": {"query", "content_type", "product", "limit", "offset"},
            "rhokp_get_document": {"identifier", "max_chars"},
            "rhokp_get_cve": {"cve_id", "max_chars"},
            "rhokp_get_erratum": {"advisory_id", "max_chars"},
        }
        if name not in allowed_arguments:
            raise InputError("unknown tool")
        unexpected = set(arguments) - allowed_arguments[name]
        if unexpected:
            raise InputError("unexpected arguments: {}".format(", ".join(sorted(unexpected))))
        try:
            if name == "rhokp_health":
                data = self.client.health()
            elif name == "rhokp_search":
                data = self.client.search(**arguments)
            elif name == "rhokp_get_document":
                data = self.client.get_document(**arguments)
            elif name == "rhokp_get_cve":
                data = self.client.get_cve(**arguments)
            else:
                data = self.client.get_erratum(**arguments)
            return {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "structuredContent": data,
                "isError": False,
            }
        except (InputError, BackendError) as exc:
            return {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            }

    @staticmethod
    def _result(request_id: Any, result: Any) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> Dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


class McpRequestHandler(BaseHTTPRequestHandler):
    server_version = SERVER_NAME
    sys_version = ""

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("http client=%s " + fmt, self.client_address[0], *args)

    @property
    def app(self) -> McpApplication:
        return getattr(self.server, "app")

    @property
    def bearer_token(self) -> str:
        return getattr(self.server, "bearer_token")

    @property
    def allowed_origins(self) -> Sequence[str]:
        return getattr(self.server, "allowed_origins")

    def _json_response(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _empty_response(self, status: int) -> None:
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _authorized(self) -> bool:
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + self.bearer_token
        return hmac.compare_digest(supplied, expected)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        return origin in self.allowed_origins

    def do_GET(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            try:
                payload = self.app.client.health()
                self._json_response(HTTPStatus.OK, payload)
            except Exception:
                self._json_response(HTTPStatus.SERVICE_UNAVAILABLE, {"status": "unavailable"})
            return
        if path != "/mcp":
            self._empty_response(HTTPStatus.NOT_FOUND)
            return
        if not self._origin_allowed():
            self._empty_response(HTTPStatus.FORBIDDEN)
            return
        if not self._authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Bearer realm="rhokp-mcp"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED)
        self.send_header("Allow", "POST")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_DELETE(self) -> None:
        self._empty_response(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_POST(self) -> None:
        started = time.monotonic()
        path = urllib.parse.urlsplit(self.path).path
        if path != "/mcp":
            self._empty_response(HTTPStatus.NOT_FOUND)
            return
        if not self._origin_allowed():
            self._empty_response(HTTPStatus.FORBIDDEN)
            return
        if not self._authorized():
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Bearer realm="rhokp-mcp"')
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._empty_response(HTTPStatus.BAD_REQUEST)
            return
        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._empty_response(HTTPStatus.REQUEST_ENTITY_TOO_LARGE if content_length > MAX_REQUEST_BYTES else HTTPStatus.BAD_REQUEST)
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._empty_response(HTTPStatus.UNSUPPORTED_MEDIA_TYPE)
            return
        body = self.rfile.read(content_length)
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_response(HTTPStatus.BAD_REQUEST, McpApplication._error(None, -32700, "Parse error"))
            return
        response = self.app.handle(message)
        method = message.get("method", "invalid") if isinstance(message, dict) else "invalid"
        if response is None:
            self._empty_response(HTTPStatus.ACCEPTED)
        else:
            self._json_response(HTTPStatus.OK, response)
        logging.info("mcp method=%s elapsed_ms=%d", method, int((time.monotonic() - started) * 1000))


def _read_token() -> str:
    token_file = os.environ.get("MCP_TOKEN_FILE")
    if not token_file:
        credential_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if credential_dir:
            token_file = os.path.join(credential_dir, "mcp_token")
    if not token_file:
        raise RuntimeError("MCP_TOKEN_FILE or a systemd mcp_token credential is required")
    with open(token_file, "r", encoding="utf-8") as stream:
        token = stream.read().strip()
    if len(token) < 32 or any(character.isspace() for character in token):
        raise RuntimeError("MCP bearer token is invalid")
    return token


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18081)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = RhokpClient(
        os.environ.get("RHOKP_BASE_URL", "http://127.0.0.1:18080"),
        os.environ.get("RHOKP_SOURCE_BASE_URL", ""),
        os.environ.get("RHOKP_IMAGE_DIGEST", ""),
        os.environ.get("RHOKP_SNAPSHOT_DATE", ""),
    )
    server = ThreadingHTTPServer((args.host, args.port), McpRequestHandler)
    server.daemon_threads = True
    setattr(server, "app", McpApplication(client))
    setattr(server, "bearer_token", _read_token())
    allowed = [origin.strip() for origin in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    setattr(server, "allowed_origins", tuple(allowed))
    logging.info("starting %s version=%s host=%s port=%d", SERVER_NAME, SERVER_VERSION, args.host, args.port)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
