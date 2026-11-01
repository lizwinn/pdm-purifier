# SPDX-License-Identifier: MIT
"""Unit tests of cli/pdm_purifier_cli.py."""

import json
import tempfile
import unittest
from pathlib import Path

import pdm_purifier_cli as cli


class Lockfile(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "pdm.lock").write_text("lock\n")
        (self.root / "pyproject.toml").write_text("project\n")

    def tearDown(self) -> None:
        self.dir.cleanup()

    def write(self, text: str) -> None:
        (self.root / cli.LOCKFILE).write_text(text)

    def test_missing_lockfile_is_not_current(self) -> None:
        self.assertFalse(cli.lock_is_current(self.root))

    def test_current_lockfile(self) -> None:
        self.write(json.dumps({"inputsHash": cli.inputs_hash(self.root)}))
        self.assertTrue(cli.lock_is_current(self.root))

    def test_stale_lockfile(self) -> None:
        self.write(json.dumps({"inputsHash": cli.inputs_hash(self.root)}))
        (self.root / "pyproject.toml").write_text("changed\n")
        self.assertFalse(cli.lock_is_current(self.root))

    def test_malformed_lockfile_names_the_fix(self) -> None:
        self.write("{ not json")
        with self.assertRaises(cli.Error) as raised:
            cli.lock_is_current(self.root)
        self.assertIn("pdm-purifier lock", str(raised.exception))

    def test_lockfile_of_the_wrong_shape(self) -> None:
        self.write("[1, 2]")
        with self.assertRaises(cli.Error):
            cli.lock_is_current(self.root)


class SourceRoot(unittest.TestCase):
    def test_includes_local_packages_outside_the_project(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            top = Path(directory)
            root = top / "app"
            (top / "shared").mkdir()
            root.mkdir()
            (root / "pdm.lock").write_text('[[package]]\nname = "shared"\npath = "../shared"\n')
            src, project_dir = cli.source_root(root)
            self.assertEqual(src, top.resolve())
            self.assertEqual(project_dir, "app")

    def test_project_alone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pdm.lock").write_text('[[package]]\nname = "a"\nversion = "1"\n')
            self.assertEqual(cli.source_root(root), (root.resolve(), "."))


if __name__ == "__main__":
    unittest.main()
