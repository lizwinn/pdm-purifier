#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Runs `pdm-purifier lock` against the network on a copy of each fixture,
# and checks that it reproduces the committed pdm-purifier.lock.json. Run it
# from the repository root:
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#gcc' 'nixpkgs#git' -c tests/lock-run.sh
set -euo pipefail

repo=$(pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv

for fixture in simple sources vcs update; do
  echo "== $fixture"
  cp -r "$repo/tests/fixtures/$fixture" "$work/$fixture"
  (cd "$work/$fixture" && pdm-purifier lock)
  diff -u "$repo/tests/fixtures/$fixture/pdm-purifier.lock.json" "$work/$fixture/pdm-purifier.lock.json"
done

echo "the lock run reproduced every fixture's pdm-purifier.lock.json"
