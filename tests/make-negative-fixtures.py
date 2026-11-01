# SPDX-License-Identifier: MIT
"""Writes tests/negative/tampered-hash from tests/fixtures/simple.

The copy has the hash of attrs' wheel in pdm.lock changed, as if someone
had edited pdm.lock by hand, and an inputsHash in pdm-purifier.lock.json
recomputed to match, so the lockfile passes the Nix library's check and the
build reaches PDM, which must refuse the served wheel. Run it from the
repository root after relocking the simple fixture:

    python3 tests/make-negative-fixtures.py
"""

import hashlib
import json
import re
import shutil
from pathlib import Path

source = Path("tests/fixtures/simple")
target = Path("tests/negative/tampered-hash")
shutil.rmtree(target, ignore_errors=True)
shutil.copytree(source, target, ignore=shutil.ignore_patterns(".venv", ".pdm-python", ".pdm-purifier"))

lock = (target / "pdm.lock").read_text()
tampered, count = re.subn(
    r'(\{file = "attrs-[^"]+\.whl", hash = "sha256:)[0-9a-f]{64}',
    lambda m: m.group(1) + "0" * 64,
    lock,
)
assert count == 1, count
(target / "pdm.lock").write_text(tampered)

purifier = json.loads((target / "pdm-purifier.lock.json").read_text())
digest = hashlib.sha256()
digest.update((target / "pdm.lock").read_bytes())
digest.update((target / "pyproject.toml").read_bytes())
purifier["inputsHash"] = digest.hexdigest()
(target / "pdm-purifier.lock.json").write_text(json.dumps(purifier, indent=2, sort_keys=True) + "\n")
