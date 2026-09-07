# AI-Author: Codex (OpenAI model not exposed by runtime)
"""Offline tests using synthetic credentials only."""

import os
from pathlib import Path
import tempfile
import unittest

from normalize_access_key import normalize


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Path(self.directory.name) / "input"
        self.destination = Path(self.directory.name) / "output"

    def stage(self, payload):
        self.source.write_bytes(payload)
        self.source.chmod(0o600)

    def test_terminal_newlines_and_permissions(self):
        key = b"synthetic-access-key-1234567890"
        for ending in (b"", b"\n", b"\r\n"):
            with self.subTest(ending=ending):
                self.stage(key + ending)
                normalize(str(self.source), str(self.destination))
                self.assertEqual(self.destination.read_bytes(), key)
                self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)
                self.destination.unlink()

    def test_malformed_rejected_without_output(self):
        for payload in (b"short", b"x" * 24 + b"\n\n", b"x" * 24 + b"\r",
                        b"x" * 24 + b"\x00", b"x" * 24 + b" embedded", b"x" * 65537):
            with self.subTest(payload_length=len(payload)):
                self.stage(payload)
                with self.assertRaises(ValueError):
                    normalize(str(self.source), str(self.destination))
                self.assertFalse(self.destination.exists())

    def test_world_readable_rejected(self):
        self.stage(b"x" * 24)
        self.source.chmod(0o644)
        with self.assertRaises(ValueError):
            normalize(str(self.source), str(self.destination))

    def test_destination_preserved(self):
        self.stage(b"x" * 24)
        self.destination.write_bytes(b"existing")
        with self.assertRaises(FileExistsError):
            normalize(str(self.source), str(self.destination))
        self.assertEqual(self.destination.read_bytes(), b"existing")

    def test_symlink_source_rejected(self):
        self.stage(b"x" * 24)
        link = Path(self.directory.name) / "link"
        os.symlink(self.source, link)
        with self.assertRaises(OSError):
            normalize(str(link), str(self.destination))


if __name__ == "__main__":
    unittest.main()
