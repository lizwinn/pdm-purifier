# SPDX-License-Identifier: MIT
"""What the pdm-purifier plugin does to PDM.

It puts the transport that PDM_PURIFIER_MODE selects under every HTTP
session PDM builds (pdm_purifier.transport), serves Mercurial, Subversion
and Bazaar checkouts from the store in serve mode, and adds the command
`pdm purifier lock` (pdm_purifier.lock).
"""

from __future__ import annotations

import argparse
from typing import Any

from pdm.cli.commands.base import BaseCommand
from pdm.exceptions import PdmUsageError

from pdm_purifier import transport


class PurifierCommand(BaseCommand):
    """Lock the downloads of this project so that Nix can build it offline"""

    name = "purifier"

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        actions = parser.add_subparsers(dest="purifier_action", metavar="ACTION")
        actions.required = True
        actions.add_parser(
            "lock",
            help="write pdm-purifier.lock.json (run it through `pdm-purifier lock`)",
        )

    def handle(self, project: Any, options: argparse.Namespace) -> None:
        from pdm_purifier.lock import LockError, lock

        if options.purifier_action == "lock":
            try:
                path = lock(project)
            except LockError as error:
                raise PdmUsageError(f"pdm-purifier: {error}") from None
            project.core.ui.echo(f"Wrote {path}")


def _patch_sessions() -> None:
    from pdm.environments import base

    build_session = base.BaseEnvironment._build_session
    if getattr(build_session, "_pdm_purifier", False):
        return

    def _build_session(self: Any, sources: Any = None, mounts: Any = None) -> Any:
        session = build_session(self, sources, mounts)
        transport.install(session)
        return session

    _build_session._pdm_purifier = True  # type: ignore[attr-defined]
    base.BaseEnvironment._build_session = _build_session  # type: ignore[method-assign]


def _patch_version_control() -> None:
    """In serve mode, a Mercurial, Subversion or Bazaar dependency comes from
    its locked checkout in the store. Git needs no patch: its locked
    checkouts keep their .git directory, and git's `url.<path>.insteadOf`
    sends the clone there."""
    import os
    import shutil
    from pathlib import Path

    from unearth.vcs.base import VersionControl

    fetch = VersionControl.fetch
    get_revision = VersionControl.get_revision
    if getattr(fetch, "_pdm_purifier", False):
        return
    served: dict[str, str] = {}

    def locked(name: str, url: str) -> dict | None:
        if os.environ.get(transport.MODE_ENV) != "serve" or name == "git":
            return None
        for entry in transport._manifest().get("vcs", []):
            if entry["vcs"] == name and entry["url"] == url:
                return entry
        raise RuntimeError(
            f"pdm-purifier: {name} repository {url} is not in pdm-purifier.lock.json, and this PDM is offline. "
            "Run `pdm-purifier lock`."
        )

    def patched_fetch(self: Any, link: Any, location: Path) -> None:
        url, _, _ = self.get_url_and_rev_options(link)
        entry = locked(self.name, url.secret if hasattr(url, "secret") else str(url))
        if entry is None:
            return fetch(self, link, location)
        if location.exists():
            shutil.rmtree(location)
        shutil.copytree(entry["store"], location, symlinks=True)
        for path in [location, *location.rglob("*")]:
            if not path.is_symlink():
                path.chmod(path.stat().st_mode | 0o200)
        from pdm_purifier.lock import write_pkg_info

        subdirectory = entry.get("subdirectory")
        write_pkg_info(location / subdirectory if subdirectory else location, entry["name"], entry["version"])
        served[str(Path(location).resolve())] = entry["rev"]
        return None

    def patched_get_revision(self: Any, location: Path) -> str:
        rev = served.get(str(Path(location).resolve()))
        return rev if rev is not None else get_revision(self, location)

    patched_fetch._pdm_purifier = True  # type: ignore[attr-defined]
    VersionControl.fetch = patched_fetch  # type: ignore[method-assign]
    for backend in VersionControl.__subclasses__():
        if backend.name != "git" and "get_revision" in backend.__dict__:
            original = backend.get_revision

            def backend_get_revision(self: Any, location: Path, _original: Any = original) -> str:
                rev = served.get(str(Path(location).resolve()))
                return rev if rev is not None else _original(self, location)

            backend.get_revision = backend_get_revision  # type: ignore[method-assign]
    VersionControl.get_revision = patched_get_revision  # type: ignore[method-assign]


def main(core: Any) -> None:
    _patch_sessions()
    _patch_version_control()
    core.register_command(PurifierCommand, "purifier")
