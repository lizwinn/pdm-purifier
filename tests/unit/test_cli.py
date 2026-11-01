# SPDX-License-Identifier: MIT
"""Unit tests of cli/pdm_purifier_cli.py."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
        self.assertFalse(cli.lock_is_current(self.root, self.root / cli.LOCKFILE))

    def test_current_lockfile(self) -> None:
        self.write(json.dumps({"inputsHash": cli.inputs_hash(self.root)}))
        self.assertTrue(cli.lock_is_current(self.root, self.root / cli.LOCKFILE))

    def test_stale_lockfile(self) -> None:
        self.write(json.dumps({"inputsHash": cli.inputs_hash(self.root)}))
        (self.root / "pyproject.toml").write_text("changed\n")
        self.assertFalse(cli.lock_is_current(self.root, self.root / cli.LOCKFILE))

    def test_malformed_lockfile_names_the_fix(self) -> None:
        self.write("{ not json")
        with self.assertRaises(cli.Error) as raised:
            cli.lock_is_current(self.root, self.root / cli.LOCKFILE)
        self.assertIn("pdm-purifier lock", str(raised.exception))

    def test_lockfile_of_the_wrong_shape(self) -> None:
        self.write("[1, 2]")
        with self.assertRaises(cli.Error):
            cli.lock_is_current(self.root, self.root / cli.LOCKFILE)


class LockfilePath(unittest.TestCase):
    def test_option_then_variable_then_project(self) -> None:
        root = Path("/project")
        with mock.patch.dict(os.environ, {"PDM_PURIFIER_LOCKFILE": "/outside/pdm-purifier.lock.json"}):
            self.assertEqual(cli.lockfile_path(root, Path("/given.json")), Path("/given.json"))
            self.assertEqual(cli.lockfile_path(root, None), Path("/outside/pdm-purifier.lock.json"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(cli.lockfile_path(root, None), root / cli.LOCKFILE)

    def test_roots_lie_beside_the_lockfile(self) -> None:
        self.assertEqual(cli.state_dir(Path("/outside/pdm-purifier.lock.json")), Path("/outside/.pdm-purifier"))


class LocalDistributions(unittest.TestCase):
    def test_project_and_path_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "app"
            (root / "libs" / "Shared_Lib").mkdir(parents=True)
            (root / "pyproject.toml").write_text('[project]\nname = "My.App"\n[build-system]\nrequires = []\n')
            (root / "libs" / "Shared_Lib" / "pyproject.toml").write_text('[project]\nname = "Shared_Lib"\n')
            (root / "pdm.lock").write_text('[[package]]\nname = "shared-lib"\npath = "libs/Shared_Lib"\n')
            self.assertEqual(cli.local_distributions(root), {"my-app": ".", "shared-lib": "libs/Shared_Lib"})

    def test_project_that_is_not_a_distribution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "pyproject.toml").write_text('[project]\nname = "app"\n')
            (root / "pdm.lock").write_text("")
            self.assertEqual(cli.local_distributions(root), {})


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
