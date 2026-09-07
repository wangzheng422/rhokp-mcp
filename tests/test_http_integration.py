# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Real loopback HTTP tests; no external backend or credentials required."""
import http.client
import json
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from mcp import rhokp_mcp_server as server


class FakeBackend(server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        payload = json.dumps({"response": {"numFound": 7, "docs": []}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


class HttpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = server.ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        cls.httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.McpRequestHandler)
        cls.httpd.app = server.McpApplication(server.RhokpClient(
            "http://127.0.0.1:{}".format(cls.backend.server_port), "", "", ""))
        cls.httpd.bearer_token = "synthetic-test-only-token-" + "x" * 32
        cls.httpd.allowed_origins = ("https://client.example.com",)
        cls.threads = []
        for httpd in (cls.backend, cls.httpd):
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for httpd in (cls.httpd, cls.backend):
            httpd.shutdown()
            httpd.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)

    def request(self, method="POST", path="/mcp", payload=None, authorized=True, origin=None):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer " + self.httpd.bearer_token
        if origin:
            headers["Origin"] = origin
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_port, timeout=3)
        try:
            connection.request(method, path, json.dumps(payload or {}), headers)
            response = connection.getresponse()
            body = response.read()
            return response.status, json.loads(body) if body else None
        finally:
            connection.close()

    def test_auth_origin_initialize_and_discovery(self):
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "2025-03-26"}}
        self.assertEqual(self.request(payload=initialize, authorized=False)[0], 401)
        self.assertEqual(self.request(payload=initialize, origin="https://untrusted.example.com")[0], 403)
        status, body = self.request(payload=initialize)
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["protocolVersion"], "2025-03-26")
        status, body = self.request(payload={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["result"]["tools"]), 5)

    def test_readiness_and_tool_reach_real_http_backend(self):
        status, body = self.request(method="GET", path="/healthz", authorized=False)
        self.assertEqual(status, 200)
        self.assertEqual(body["documents"], 7)
        status, body = self.request(payload={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                          "params": {"name": "rhokp_health", "arguments": {}}})
        self.assertEqual(status, 200)
        self.assertFalse(body["result"]["isError"])
        self.assertEqual(body["result"]["structuredContent"]["documents"], 7)

    def test_notification_and_get_transport(self):
        self.assertEqual(self.request(payload={"jsonrpc": "2.0", "method": "notifications/initialized"})[0], 202)
        self.assertEqual(self.request(method="GET")[0], 405)

    def test_token_file_validation(self):
        with tempfile.NamedTemporaryFile(mode="w+") as secret:
            with patch.dict(os.environ, {"MCP_TOKEN_FILE": secret.name}):
                secret.write(self.httpd.bearer_token + "\n")
                secret.flush()
                self.assertEqual(server._read_token(), self.httpd.bearer_token)
                secret.seek(0)
                secret.truncate()
                secret.write("short")
                secret.flush()
                with self.assertRaises(RuntimeError):
                    server._read_token()


class RedirectIntegrationTests(unittest.TestCase):
    def test_redirects_checked_before_following_for_documents_and_search(self):
        target_hits = []
        backend_hits = []

        class Trap(server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                target_hits.append(self.path)
                self.send_response(200)
                self.end_headers()

        class RedirectBackend(server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                backend_hits.append(self.path)
                if self.path == "/solutions/final":
                    body = b"<html><title>Fixture</title><p>Local content</p></html>"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(302)
                self.send_header("Location", "/solutions/final" if self.path ==
                                 "/solutions/local" else self.server.destination)
                self.end_headers()

        trap = server.ThreadingHTTPServer(("127.0.0.1", 0), Trap)
        backend = server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectBackend)
        backend.destination = "http://127.0.0.1:{}/trap".format(trap.server_port)
        threads = []
        try:
            for httpd in (trap, backend):
                thread = threading.Thread(target=httpd.serve_forever, daemon=True)
                thread.start()
                threads.append(thread)
            client = server.RhokpClient(
                "http://127.0.0.1:{}".format(backend.server_port), "", "", "")
            for operation in (lambda: client.get_document("/solutions/external"),
                              lambda: client.search("fixture")):
                with self.assertRaisesRegex(server.BackendError, "configured origin"):
                    operation()
            self.assertEqual(target_hits, [], "Rejected redirect must never contact target")
            client.get_document("/solutions/local")
            self.assertIn("/solutions/final", backend_hits)
        finally:
            for httpd in (backend, trap):
                httpd.shutdown()
                httpd.server_close()
            for thread in threads:
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
