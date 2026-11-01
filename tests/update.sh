#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# The CI job conformance-update: `pdm-purifier update` on a copy of the
# update fixture, whose pdm.lock pins six 1.15.0 while pyproject.toml allows
# six>=1.15, moves six to a newer version. Both lockfiles then pass their
# stale checks: `pdm lock --check` for pdm.lock, and `pdm-purifier prefetch`,
# which builds the project's manifest with Nix, for pdm-purifier.lock.json.
# Run it from the repository root:
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#git' -c tests/update.sh
set -euo pipefail

repo=$(pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv
export PDM_CACHE_DIR="$work/pdm-cache"

cp -r "$repo/tests/fixtures/update" "$work/project"
cd "$work/project"

six_version() {
  python3 -c 'import sys, tomllib; print(next(p["version"] for p in tomllib.load(open("pdm.lock", "rb"))["package"] if p["name"] == "six"))'
}

[ "$(six_version)" = "1.15.0" ]
pdm-purifier update
updated=$(six_version)
echo "six: 1.15.0 -> $updated"
[ "$updated" != "1.15.0" ]
PDM_PURIFIER_MODE=off pdm lock --check
pdm-purifier prefetch

echo "update test passed"
