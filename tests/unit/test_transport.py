# SPDX-License-Identifier: MIT
"""Unit tests of the transports in plugin/src/pdm_purifier/transport.py."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from pdm_purifier.transport import (
    RecordingTransport,
    ServingTransport,
    is_distribution,
    normalize_name,
)


class Names(unittest.TestCase):
    def test_normalize_name(self) -> None:
        self.assertEqual(normalize_name("Foo_Bar.baz"), "foo-bar-baz")
        self.assertEqual(normalize_name("pdm-backend"), "pdm-backend")

    def test_is_distribution(self) -> None:
        for url in [
            "https://x/a-1.0-py3-none-any.whl",
            "https://x/a-1.0.tar.gz",
            "https://x/a-1.0.zip",
            "https://x/a-1.0.tar.gz#sha256=00",
        ]:
            self.assertTrue(is_distribution(httpx.URL(url)), url)
        for url in ["https://pypi.org/simple/a/", "https://x/a-1.0-py3-none-any.whl.metadata"]:
            self.assertFalse(is_distribution(httpx.URL(url)), url)


class Serving(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.file = Path(self.dir.name) / "a-1.0-py3-none-any.whl"
        self.file.write_bytes(b"wheel")
        self.url = "https://files.example/a-1.0-py3-none-any.whl"
        entry = {
            "file": self.file.name,
            "url": self.url,
            "sha256": hashlib.sha256(b"wheel").hexdigest(),
            "requiresPython": ">=3.9",
        }
        self.transport = ServingTransport(
            {
                "files": {self.url: str(self.file)},
                "projects": {"a": [entry]},
                "findLinks": ["https://links.example/dist/"],
            }
        )
        self.client = httpx.Client(transport=self.transport)

    def tearDown(self) -> None:
        self.client.close()
        self.dir.cleanup()

    def test_serves_a_locked_file(self) -> None:
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"wheel")

    def test_serves_a_locked_file_with_a_fragment(self) -> None:
        response = self.client.get(self.url + "#sha256=00")
        self.assertEqual(response.content, b"wheel")

    def test_index_page_lists_only_locked_files(self) -> None:
        for url in ["https://pypi.org/simple/a/", "https://mirror.example/pypi/simple/A/"]:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            page = json.loads(response.content)
            self.assertEqual(page["name"], "a")
            self.assertEqual([f["filename"] for f in page["files"]], [self.file.name])
            self.assertEqual(page["files"][0]["hashes"]["sha256"], hashlib.sha256(b"wheel").hexdigest())
            self.assertEqual(page["files"][0]["requires-python"], ">=3.9")

    def test_find_links_page_lists_every_file(self) -> None:
        response = self.client.get("https://links.example/dist")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.file.name, response.text)
        self.assertIn("#sha256=", response.text)

    def test_anything_else_is_refused(self) -> None:
        for url in ["https://pypi.org/simple/b/", "https://files.example/b-1.0.tar.gz"]:
            self.assertEqual(self.client.get(url).status_code, 404, url)


class Recording(unittest.TestCase):
    def test_records_distribution_files_only(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=b"body:" + request.url.path.encode())

        upstream = httpx.MockTransport(handler)
        with tempfile.TemporaryDirectory() as directory:
            record = Path(directory) / "record.jsonl"
            transport = RecordingTransport(lambda url: upstream, record)
            with httpx.Client(transport=transport) as client:
                page = client.get("https://pypi.org/simple/a/")
                wheel = client.get("https://files.example/a-1.0-py3-none-any.whl")
            self.assertEqual(page.content, b"body:/simple/a/")
            self.assertEqual(wheel.content, b"body:/a-1.0-py3-none-any.whl")
            entries = [json.loads(line) for line in record.read_text().splitlines()]
        self.assertEqual(
            entries,
            [
                {
                    "url": "https://files.example/a-1.0-py3-none-any.whl",
                    "sha256": hashlib.sha256(b"body:/a-1.0-py3-none-any.whl").hexdigest(),
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
