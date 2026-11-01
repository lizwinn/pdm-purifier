# SPDX-License-Identifier: MIT
"""The PDM plugin of pdm-purifier.

PDM loads it from the `pdm` entry point group. It puts the transport that
PDM_PURIFIER_MODE selects under every HTTP session PDM builds
(pdm_purifier.transport), and adds the command `pdm purifier lock`
(pdm_purifier.lock).
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


def main(core: Any) -> None:
    _patch_sessions()
    core.register_command(PurifierCommand, "purifier")
