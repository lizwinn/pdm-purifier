# SPDX-License-Identifier: MIT
"""The PDM plugin of pdm-purifier.

PDM loads `main` from the `pdm` entry point group. The code that touches
PDM is in pdm_purifier.plugin, so that pdm_purifier.transport and
pdm_purifier.lock's helpers import without PDM.
"""

from __future__ import annotations

from typing import Any


def main(core: Any) -> None:
    from pdm_purifier.plugin import main as install

    install(core)
