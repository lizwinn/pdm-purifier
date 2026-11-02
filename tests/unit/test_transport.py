# SPDX-License-Identifier: MIT
"""Unit tests of the transports in plugin/src/pdm_purifier/transport.py."""

import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from pdm_purifier import transport
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


class Activation(unittest.TestCase):
    """A project that `pdm-purifier prefetch` prepared is served from its
    manifest while pdm.lock and pyproject.toml keep the prefetched hash."""

    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "pdm-purifier.lock.json").write_text("{}\n")
        transport._warned_unlocked.clear()
        (self.root / "pdm.lock").write_text("lock\n")
        (self.root / "pyproject.toml").write_text("project\n")
        state = self.root / ".pdm-purifier"
        state.mkdir()
        manifest = {"git": [{"url": "https://example.org/a.git", "store": "/nix/store/a"}]}
        (state / "manifest").write_text(json.dumps(manifest))
        (state / "inputs").write_text(transport.inputs_hash(self.root) + "\n")
        transport._manifest_cache = None
        self.addCleanup(setattr, transport, "_manifest_cache", None)
        self.addCleanup(self.dir.cleanup)

    def activate(self, env: dict[str, str]) -> dict[str, str]:
        with mock.patch.dict(os.environ, env, clear=True):
            transport.activate(self.root)
            return dict(os.environ)

    def test_prefetched_project_is_served(self) -> None:
        env = self.activate({})
        self.assertEqual(env["PDM_PURIFIER_MODE"], "serve")
        self.assertEqual(env["GIT_CONFIG_KEY_1"], "url./nix/store/a.insteadOf")
        self.assertEqual(env["GIT_CONFIG_VALUE_1"], "https://example.org/a.git")

    def test_changed_project_stops(self) -> None:
        (self.root / "pyproject.toml").write_text("changed\n")
        with self.assertRaisesRegex(RuntimeError, "pdm-purifier lock"):
            self.activate({})

    def test_no_lock_warns_even_when_old_cache_remains(self) -> None:
        (self.root / "pdm-purifier.lock.json").unlink()
        warning = io.StringIO()
        with mock.patch("sys.stderr", warning):
            self.assertNotIn("PDM_PURIFIER_MODE", self.activate({}))
        self.assertIn("warning:", warning.getvalue())
        self.assertIn("impurely", warning.getvalue())

    def test_existing_lock_without_prefetch_stops(self) -> None:
        (self.root / ".pdm-purifier" / "inputs").unlink()
        with self.assertRaisesRegex(RuntimeError, "pdm-purifier prefetch"):
            self.activate({})

    def test_external_lockfile_is_served_from_beside_it(self) -> None:
        outside = Path(self.dir.name) / "outside"
        outside.mkdir()
        (self.root / ".pdm-purifier").rename(outside / ".pdm-purifier")
        (self.root / "pdm-purifier.lock.json").rename(outside / "pdm-purifier.lock.json")
        self.assertNotIn("PDM_PURIFIER_MODE", self.activate({}))
        env = self.activate({"PDM_PURIFIER_LOCKFILE": str(outside / "pdm-purifier.lock.json")})
        self.assertEqual(env["PDM_PURIFIER_MODE"], "serve")

    def test_outside_pdm_lock_named_by_pdm_is_the_one_compared(self) -> None:
        outside = Path(self.dir.name) / "outside.lock"
        outside.write_text("lock\n")
        (self.root / "pdm.lock").write_text("tree copy changed\n")
        with self.assertRaisesRegex(RuntimeError, "pdm-purifier lock"):
            self.activate({})
        env = self.activate({"PDM_LOCKFILE": str(outside)})
        self.assertEqual(env["PDM_PURIFIER_MODE"], "serve")

    def test_mode_off_runs_online(self) -> None:
        self.assertEqual(self.activate({"PDM_PURIFIER_MODE": "off"})["PDM_PURIFIER_MODE"], "off")


if __name__ == "__main__":
    unittest.main()
