# SPDX-License-Identifier: MIT
"""Unit tests of the helpers of plugin/src/pdm_purifier/lock.py."""

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from pdm_purifier.lock import (
    content_hash,
    has_linux_wheel,
    inputs_hash,
    is_sdist,
    is_universal_wheel,
    make_editable,
    name_and_version,
    sri,
    write_pkg_info,
)


class FileNames(unittest.TestCase):
    def test_name_and_version(self) -> None:
        self.assertEqual(name_and_version("attrs-26.1.0-py3-none-any.whl"), ("attrs", "26.1.0"))
        self.assertEqual(name_and_version("pdm_backend-2.5.0.tar.gz"), ("pdm-backend", "2.5.0"))
        self.assertEqual(name_and_version("docopt-0.6.2.tar.gz"), ("docopt", "0.6.2"))
        self.assertEqual(name_and_version("six-1.17.0.zip"), ("six", "1.17.0"))
        self.assertIsNone(name_and_version("index.html"))

    def test_universal_wheels(self) -> None:
        self.assertTrue(is_universal_wheel("six-1.17.0-py2.py3-none-any.whl"))
        self.assertFalse(is_universal_wheel("xxhash-4.0.2-cp314-cp314-manylinux_2_17_x86_64.whl"))
        self.assertFalse(is_universal_wheel("docopt-0.6.2.tar.gz"))

    def test_linux_wheels_by_architecture_and_python(self) -> None:
        python = (3, 14)
        manylinux = "cryptography-50.0.2-cp311-abi3-manylinux_2_28_{}.whl"
        self.assertTrue(has_linux_wheel(manylinux.format("x86_64"), "x86_64", python))
        self.assertFalse(has_linux_wheel(manylinux.format("x86_64"), "aarch64", python))
        self.assertTrue(has_linux_wheel("six-1.17.0-py2.py3-none-any.whl".replace("any", "linux_aarch64"), "aarch64", python))
        # The stable ABI of a newer CPython, and a wheel for another CPython.
        self.assertFalse(has_linux_wheel("a-1-cp315-abi3-manylinux_2_17_x86_64.whl", "x86_64", python))
        self.assertFalse(has_linux_wheel("a-1-cp313-cp313-manylinux_2_17_x86_64.whl", "x86_64", python))
        self.assertTrue(has_linux_wheel("a-1-cp314-cp314-musllinux_1_2_x86_64.whl", "x86_64", python))
        self.assertFalse(has_linux_wheel("a-1-cp314-cp314-macosx_11_0_arm64.whl", "aarch64", python))
        self.assertFalse(has_linux_wheel("a-1.tar.gz", "x86_64", python))

    def test_sdists(self) -> None:
        self.assertTrue(is_sdist("docopt-0.6.2.tar.gz"))
        self.assertFalse(is_sdist("six-1.17.0-py2.py3-none-any.whl"))


class Hashes(unittest.TestCase):
    def test_sri(self) -> None:
        digest = hashlib.sha256(b"x").hexdigest()
        self.assertEqual(sri(digest), "sha256-" + base64.b64encode(hashlib.sha256(b"x").digest()).decode())

    def test_inputs_hash_covers_pdm_lock_then_pyproject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pdm.lock").write_text("lock\n")
            (root / "pyproject.toml").write_text("project\n")
            self.assertEqual(inputs_hash(root), hashlib.sha256(b"lock\nproject\n").hexdigest())

    def test_content_hash_leaves_itself_out(self) -> None:
        # The compact, key-sorted JSON that Nix's builtins.toJSON makes.
        data = {"version": 2, "b": ["é", 1], "a": {"y": None, "x": True}}
        expected = hashlib.sha256('{"a":{"x":true,"y":null},"b":["é",1],"version":2}'.encode()).hexdigest()
        self.assertEqual(content_hash(data), expected)
        self.assertEqual(content_hash(data | {"contentHash": "0"}), expected)


class Builds(unittest.TestCase):
    def test_copy_from_the_store_gets_a_time_that_zip_files_hold(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            checkout = Path(directory)
            source = checkout / "pkg" / "__init__.py"
            source.parent.mkdir()
            source.write_text("")
            source.chmod(0o444)
            for path in (source, source.parent, checkout):
                os.utime(path, (1, 1))
            make_editable(checkout)
            for path in (source, source.parent, checkout):
                self.assertGreaterEqual(path.stat().st_mtime, 315532800)
            self.assertTrue(source.stat().st_mode & 0o200)

    def test_write_pkg_info_keeps_an_existing_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            write_pkg_info(source, "a", "1.0")
            self.assertEqual((source / "PKG-INFO").read_text(), "Metadata-Version: 2.1\nName: a\nVersion: 1.0\n")
            write_pkg_info(source, "a", "2.0")
            self.assertIn("Version: 1.0", (source / "PKG-INFO").read_text())


if __name__ == "__main__":
    unittest.main()
