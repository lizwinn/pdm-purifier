#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# The CI job real-world: builds PDM 2.27.0 itself, at a pinned commit, with
# pdm-purifier. It refreshes pdm.lock with `pdm lock`, because files that an
# index removed since the commit make the committed pdm.lock unusable, runs
# `pdm-purifier lock`, and builds PDM's virtual environment and its package
# in the Nix sandbox. The built `pdm` must run. Run it from the repository
# root:
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#git' 'nixpkgs#gcc' \
#     'nixpkgs#pkg-config' 'nixpkgs#libffi.dev' -c tests/real-world.sh
set -euo pipefail

repo=$(pwd)
commit=09c95b7842844f4e857c88f669e1c666db405c71
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv
export PDM_CACHE_DIR="$work/pdm-cache"

git clone --quiet https://github.com/pdm-project/pdm.git "$work/pdm"
git -C "$work/pdm" checkout --quiet "$commit"
cd "$work/pdm"

# cffi builds from its sdist during the lock run, and finds libffi through
# pkg-config.
PKG_CONFIG_PATH=$(nix build --no-link --print-out-paths 'nixpkgs#libffi.dev')/lib/pkgconfig
export PKG_CONFIG_PATH

PDM_PURIFIER_MODE=off pdm lock -G :all
pdm-purifier lock

cd "$repo"
environment=$(nix build --impure -f tests/real-world.nix --argstr repo "$repo" \
  --argstr project "$work/pdm" environment --no-link --print-out-paths)
"$environment/bin/pdm" --version
nix build --impure -f tests/real-world.nix --argstr repo "$repo" \
  --argstr project "$work/pdm" packages.pdm --no-link

echo "real-world test passed"
