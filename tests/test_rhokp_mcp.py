# AI-Author: Codex (OpenAI model not exposed by runtime)
# AI-Author: luna_worker (OpenAI gpt-5.6-luna)
"""Unit tests for the read-only RHoKP MCP adapter."""

import json
import unittest
from unittest.mock import Mock, patch

from mcp import rhokp_mcp_server as server


class RhokpClientValidationTests(unittest.TestCase):
    """Validate inputs before a backend request is made."""

    def setUp(self):
        self.client = server.RhokpClient(
            "https://offline.invalid",
            "https://source.invalid",
            "sha256:synthetic",
            "2099-01-01",
        )

    def test_query_is_normalized_and_rejects_invalid_syntax(self):
        payload = {"response": {"numFound": 0, "start": 0, "docs": []}}
        with patch.object(self.client, "_solr", return_value=payload) as solr:
            result = self.client.search("  synthetic   query  ")
        self.assertEqual(result["query"], "synthetic query")
        self.assertEqual(solr.call_args.args[0][0], ("q", "synthetic query"))

        invalid_queries = [
            None,
            123,
            "",
            "   \t\n",
            "x" * (server.MAX_QUERY_LENGTH + 1),
            "synthetic\x00query",
            "synthetic\x7fquery",
            "synthetic {!type=lucene}query",
        ]
        for query in invalid_queries:
            with self.subTest(query=repr(query)):
                with patch.object(self.client, "_solr") as solr:
                    with self.assertRaises(server.InputError):
                        self.client.search(query)
                solr.assert_not_called()

    def test_product_rejects_control_and_local_parameter_syntax(self):
        for product in (None, 123, "", "   ", "synthetic\x00product", "synthetic\x7fproduct", "synthetic {!terms f=product}product"):
            if product is None:
                continue
            with self.subTest(product=repr(product)):
                with patch.object(self.client, "_solr") as solr:
                    with self.assertRaises(server.InputError):
                        self.client.search("query", product=product)
                solr.assert_not_called()

        with patch.object(self.client, "_solr", return_value={"response": {"numFound": 0, "docs": []}}):
            with self.assertRaises(server.InputError):
                self.client.search("query", product="x" * 201)

    def test_integer_boundaries_are_inclusive_and_out_of_range_rejected(self):
        payload = {"response": {"numFound": 0, "start": 10000, "docs": []}}
        with patch.object(self.client, "_solr", return_value=payload) as solr:
            self.client.search("query", limit=1, offset=0)
            self.client.search("query", limit=10, offset=10000)
        first_params = solr.call_args_list[0].args[0]
        last_params = solr.call_args_list[1].args[0]
        self.assertIn(("rows", "1"), first_params)
        self.assertIn(("start", "0"), first_params)
        self.assertIn(("rows", "10"), last_params)
        self.assertIn(("start", "10000"), last_params)

        for name, value in (
            ("limit", 0),
            ("limit", 11),
            ("offset", -1),
            ("offset", 10001),
            ("limit", True),
            ("offset", 1.0),
        ):
            with self.subTest(name=name, value=value):
                with patch.object(self.client, "_solr") as solr:
                    with self.assertRaises(server.InputError):
                        self.client.search("query", **{name: value})
                solr.assert_not_called()

    def test_get_document_max_chars_boundaries(self):
        response = (
            b"<html><title>Synthetic document</title><p>"
            b"A bounded synthetic body.</p></html>",
            "https://offline.invalid/solutions/synthetic-document",
            {"Content-Type": "text/html; charset=utf-8"},
        )
        with patch.object(self.client, "_read", return_value=response):
            for max_chars in (500, server.MAX_DOCUMENT_CHARS):
                with self.subTest(max_chars=max_chars):
                    document = self.client.get_document(
                        "/solutions/synthetic-document", max_chars=max_chars
                    )
                    self.assertFalse(document["truncated"])

        for max_chars in (499, server.MAX_DOCUMENT_CHARS + 1, True, 1.0):
            with self.subTest(max_chars=max_chars):
                with patch.object(self.client, "_read") as read:
                    with self.assertRaises(server.InputError):
                        self.client.get_document(
                            "/solutions/synthetic-document", max_chars=max_chars
                        )
                read.assert_not_called()


class RhokpSearchTests(unittest.TestCase):
    def setUp(self):
        self.client = server.RhokpClient(
            "https://offline.invalid",
            "https://source.invalid",
            "sha256:synthetic",
            "2099-01-01",
        )
        self.payload = {
            "response": {
                "numFound": 1,
                "start": 2,
                "docs": [
                    {
                        "id": "/solutions/synthetic-1",
                        "title": "Synthetic title",
                        "documentKind": "solution",
                        "product": ["Synthetic Product"],
                        "lastModifiedDate": "2099-01-02",
                        "score": 1.5,
                    }
                ],
            },
            "highlighting": {
                "/solutions/synthetic-1": {
                    "main_content": ["<em>synthetic</em> result", "<script>ignore</script>usable"]
                }
            },
            "facet_counts": {"facet_fields": {"documentKind": ["solution", 1]}},
        }

    def test_search_builds_solr_params_and_result_metadata(self):
        with patch.object(self.client, "_solr", return_value=self.payload) as solr:
            result = self.client.search(
                "  kernel +issue ",
                content_type="SoLuTiOn",
                product="  Synthetic:Product  ",
                limit=3,
                offset=2,
            )

        params = solr.call_args.args[0]
        self.assertIn(("q", "kernel \\+issue"), params)
        self.assertIn(("defType", "edismax"), params)
        self.assertIn(("qf", "title^5 main_content resourceName^2 product^2"), params)
        self.assertIn(("rows", "3"), params)
        self.assertIn(("start", "2"), params)
        self.assertIn(("wt", "json"), params)
        self.assertIn(("hl", "true"), params)
        self.assertIn(("facet", "true"), params)
        self.assertIn(("fq", "documentKind:solution"), params)
        self.assertIn(("fq", 'product:"Synthetic\\:Product"'), params)

        self.assertEqual(result["query"], "kernel +issue")
        self.assertEqual(result["content_type"], "solution")
        self.assertEqual(result["product"], "Synthetic:Product")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["offset"], 2)
        self.assertEqual(result["returned"], 1)
        self.assertEqual(result["results"][0]["source_url"], "https://source.invalid/solutions/synthetic-1")
        self.assertEqual(result["results"][0]["snippets"], ["synthetic result", "usable"])
        self.assertEqual(result["facets"], {"content_type": [{"value": "solution", "count": 1}]})

    def test_each_content_type_adds_the_expected_filter(self):
        expected = {
            "solution": "solution",
            "article": "article",
            "documentation": "documentation",
            "cve": "Cve",
            "errata": "Errata",
        }
        payload = {"response": {"numFound": 0, "start": 0, "docs": []}}
        with patch.object(self.client, "_solr", return_value=payload) as solr:
            for supplied, solr_kind in expected.items():
                with self.subTest(content_type=supplied):
                    result = self.client.search("query", content_type=supplied)
                    params = solr.call_args.args[0]
                    self.assertEqual(result["content_type"], supplied)
                    self.assertIn(("fq", "documentKind:" + solr_kind), params)

        for content_type in ("unknown", "", 1, True):
            with self.subTest(content_type=repr(content_type)):
                with patch.object(self.client, "_solr") as solr:
                    with self.assertRaises(server.InputError):
                        self.client.search("query", content_type=content_type)
                solr.assert_not_called()


class RhokpDocumentAndIdTests(unittest.TestCase):
    def setUp(self):
        self.client = server.RhokpClient(
            "https://offline.invalid",
            "https://source.invalid",
            "sha256:synthetic",
            "2099-01-01",
        )
        self.read_response = (
            b"<html><head><title>Synthetic page</title></head>"
            b"<body><p>First paragraph.</p><script>not returned</script>"
            b"<p>Second paragraph.</p></body></html>",
            "https://offline.invalid/solutions/synthetic-page",
            {"Content-Type": "text/html; charset=utf-8"},
        )

    def test_get_document_accepts_allowed_paths_and_errata(self):
        with patch.object(self.client, "_read", return_value=self.read_response) as read:
            document = self.client.get_document("  /solutions/synthetic-page  ", max_chars=500)
            request = read.call_args.args[0]
        self.assertIsInstance(request, server.urllib.request.Request)
        self.assertEqual(request.full_url, "https://offline.invalid/solutions/synthetic-page")
        self.assertEqual(request.get_header("Accept"), "text/html")
        self.assertEqual(document["id"], "/solutions/synthetic-page")
        self.assertEqual(document["title"], "Synthetic page")
        self.assertIn("First paragraph.", document["content"])
        self.assertNotIn("not returned", document["content"])
        self.assertEqual(document["source_path"], "/solutions/synthetic-page")
        self.assertEqual(document["source_url"], "https://source.invalid/solutions/synthetic-page")

        with patch.object(self.client, "_read", return_value=self.read_response) as read:
            self.client.get_document("RHSA-2099:9999")
        request = read.call_args.args[0]
        self.assertEqual(request.full_url, "https://offline.invalid/errata/RHSA-2099:9999")

        for path in ("/solutions/synthetic-page", "/articles/synthetic-page", "/documentation/synthetic-page", "/security/cve/CVE-2099-1234"):
            with self.subTest(path=path):
                with patch.object(self.client, "_read", return_value=self.read_response) as read:
                    self.client.get_document(path)
                self.assertTrue(read.called)
                self.assertEqual(read.call_args.args[0].full_url, "https://offline.invalid" + path)

    def test_get_document_rejects_absolute_traversal_and_external_paths_before_read(self):
        invalid_identifiers = [
            "https://attacker.invalid/solutions/synthetic",
            "http://attacker.invalid/",
            "//attacker.invalid/solutions/synthetic",
            "/solutions/../etc/passwd",
            "/solutions/synthetic?redirect=https://attacker.invalid",
            "/solutions/synthetic#fragment",
            "/not-allowed/synthetic",
            "C:\\Windows\\system32",
            123,
            None,
        ]
        for identifier in invalid_identifiers:
            with self.subTest(identifier=repr(identifier)):
                with patch.object(self.client, "_read") as read:
                    with self.assertRaises(server.InputError):
                        self.client.get_document(identifier)
                read.assert_not_called()

    def test_get_document_propagates_redirect_ssrf_rejection_from_read(self):
        redirect_error = server.BackendError("RHoKP redirect left the configured origin")
        with patch.object(self.client, "_read", side_effect=redirect_error) as read:
            with self.assertRaises(server.BackendError):
                self.client.get_document("/solutions/synthetic-page")
        read.assert_called_once()

    def test_cve_and_erratum_ids_are_validated_and_normalized(self):
        with patch.object(self.client, "get_document", return_value={"ok": True}) as get_document:
            self.assertEqual(self.client.get_cve("cVe-2099-1234"), {"ok": True})
            get_document.assert_called_once_with("/security/cve/CVE-2099-1234", None)

        with patch.object(self.client, "get_document", return_value={"ok": True}) as get_document:
            self.assertEqual(self.client.get_erratum("rHbA-2099:9999"), {"ok": True})
            get_document.assert_called_once_with("RHBA-2099:9999", None)

        invalid_cves = [None, 123, "CVE-2099-123", "CVE-2099-1234x", "CVE-99-1234", "CVE-2099-1234 "]
        for cve_id in invalid_cves:
            with self.subTest(cve_id=repr(cve_id)):
                with patch.object(self.client, "get_document") as get_document:
                    with self.assertRaises(server.InputError):
                        self.client.get_cve(cve_id)
                get_document.assert_not_called()

        invalid_errata = [None, 123, "RHXX-2099:9999", "RHSA-2099-999", "RHSA-99:9999", "RHSA-2099:9999 "]
        for advisory_id in invalid_errata:
            with self.subTest(advisory_id=repr(advisory_id)):
                with patch.object(self.client, "get_document") as get_document:
                    with self.assertRaises(server.InputError):
                        self.client.get_erratum(advisory_id)
                get_document.assert_not_called()


class McpApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.app = server.McpApplication(self.client)

    def test_tool_definitions_are_read_only(self):
        definitions = server.tool_definitions()
        self.assertEqual(
            {definition["name"] for definition in definitions},
            {
                "rhokp_health",
                "rhokp_search",
                "rhokp_get_document",
                "rhokp_get_cve",
                "rhokp_get_erratum",
            },
        )
        for definition in definitions:
            with self.subTest(tool=definition["name"]):
                annotations = definition["annotations"]
                self.assertTrue(annotations["readOnlyHint"])
                self.assertFalse(annotations["destructiveHint"])
                self.assertTrue(annotations["idempotentHint"])
                self.assertFalse(annotations["openWorldHint"])

    def test_initialize_tools_list_and_unknown_method(self):
        initialized = self.app.handle(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": server.SUPPORTED_PROTOCOL_VERSIONS[-1]},
            }
        )
        self.assertEqual(initialized["result"]["protocolVersion"], server.SUPPORTED_PROTOCOL_VERSIONS[-1])
        self.assertEqual(initialized["result"]["serverInfo"]["name"], server.SERVER_NAME)
        self.assertIn("tools", initialized["result"]["capabilities"])

        listed = self.app.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        self.assertEqual(listed["result"]["tools"], server.tool_definitions())

        unknown = self.app.handle({"jsonrpc": "2.0", "id": 3, "method": "made-up"})
        self.assertEqual(unknown["error"], {"code": -32601, "message": "Method not found"})

    def test_tools_call_dispatches_and_returns_structured_content(self):
        self.client.search.return_value = {"query": "synthetic", "total": 0}
        response = self.app.handle(
            {
                "jsonrpc": "2.0",
                "id": "search-1",
                "method": "tools/call",
                "params": {"name": "rhokp_search", "arguments": {"query": "synthetic"}},
            }
        )
        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"], {"query": "synthetic", "total": 0})
        self.assertEqual(json.loads(result["content"][0]["text"]), {"query": "synthetic", "total": 0})
        self.client.search.assert_called_once_with(query="synthetic")

    def test_tool_application_errors_are_is_error_results(self):
        for exception in (
            server.InputError("invalid synthetic input"),
            server.BackendError("synthetic backend unavailable"),
        ):
            with self.subTest(exception=type(exception).__name__):
                self.client.search.reset_mock()
                self.client.search.side_effect = exception
                response = self.app.handle(
                    {
                        "jsonrpc": "2.0",
                        "id": 4,
                        "method": "tools/call",
                        "params": {"name": "rhokp_search", "arguments": {"query": "synthetic"}},
                    }
                )
                self.assertIn("result", response)
                self.assertTrue(response["result"]["isError"])
                self.assertNotIn("structuredContent", response["result"])
                self.assertEqual(response["result"]["content"][0]["type"], "text")

    def test_invalid_tool_call_and_notification_are_handled(self):
        invalid = self.app.handle(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "rhokp_search", "arguments": {"query": "synthetic", "extra": 1}},
            }
        )
        self.assertEqual(invalid["error"]["code"], -32602)
        self.assertIsNone(
            self.app.handle(
                {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
            )
        )


if __name__ == "__main__":
    unittest.main()
