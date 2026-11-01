# SPDX-License-Identifier: MIT
"""Unit tests of the helpers of plugin/src/pdm_purifier/lock.py."""

import base64
import hashlib
import tempfile
import unittest
import zipfile
from pathlib import Path

from pdm_purifier.lock import (
    inputs_hash,
    is_sdist,
    is_universal_wheel,
    name_and_version,
    sri,
    wheel_scripts,
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


class Builds(unittest.TestCase):
    def test_wheel_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "a-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as zf:
                zf.writestr(
                    "a-1.0.dist-info/entry_points.txt",
                    "[console_scripts]\nZed = a:z\nalpha = a:main\n\n[gui_scripts]\nwindow = a:gui\n",
                )
            self.assertEqual(wheel_scripts(wheel), {"console": ["Zed", "alpha"], "gui": ["window"]})

    def test_wheel_without_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            wheel = Path(directory) / "a-1.0-py3-none-any.whl"
            with zipfile.ZipFile(wheel, "w") as zf:
                zf.writestr("a/__init__.py", "")
            self.assertEqual(wheel_scripts(wheel), {"console": [], "gui": []})

    def test_write_pkg_info_keeps_an_existing_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            write_pkg_info(source, "a", "1.0")
            self.assertEqual((source / "PKG-INFO").read_text(), "Metadata-Version: 2.1\nName: a\nVersion: 1.0\n")
            write_pkg_info(source, "a", "2.0")
            self.assertIn("Version: 1.0", (source / "PKG-INFO").read_text())


if __name__ == "__main__":
    unittest.main()
