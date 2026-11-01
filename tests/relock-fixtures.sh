#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Relocks every fixture under tests/fixtures with `pdm-purifier lock`, which
# writes pdm-purifier.lock.json, and brings pdm.lock up to date first when
# it no longer matches pyproject.toml. Run it after changing a fixture's
# pyproject.toml, or after a change to the lock format, from the repository
# root:
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#gcc' 'nixpkgs#git' \
#     'nixpkgs#mercurial' 'nixpkgs#subversion' 'nixpkgs#breezy' \
#     -c tests/relock-fixtures.sh
#
# Locking checks out the fixtures' version control dependencies, so it
# needs git, hg, svn and bzr. It builds python-xxhash's C extension, so it
# needs a C compiler.
set -euo pipefail

export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv

for fixture in tests/fixtures/*/; do
  echo "== $fixture"
  (
    cd "$fixture"
    pdm-purifier lock
    rm -rf .venv .pdm-python .pdm-purifier
  )
done
