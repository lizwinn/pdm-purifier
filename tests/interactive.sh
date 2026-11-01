#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Tests the verbs of the `pdm-purifier` command that run outside the Nix
# sandbox, on a copy of the sources fixture:
#
# - after `pdm-purifier prefetch`, plain `pdm sync`, `pdm run` and
#   `pdm build` work with the network cut off and an empty PDM cache
#   (the CI job conformance-offline);
# - adding a dependency that is not locked fails with pdm-purifier's
#   message, which names the way to add it;
# - a project changed since the prefetch runs PDM the usual way, with a
#   warning;
# - with the lockfile kept outside the project, named by
#   PDM_PURIFIER_LOCKFILE, prefetch and the development loop work the same;
# - `pdm-purifier publish` uploads exactly the sdist and wheel Nix built, to
#   a local upload endpoint (tests/upload_server.py).
#
# Run it from the repository root with the CLI on PATH, a Python and a C
# compiler (xxhash compiles one):
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#gcc' 'nixpkgs#git' 'nixpkgs#util-linux' -c tests/interactive.sh
set -euo pipefail

repo=$(pwd)
work=$(mktemp -d)
trap 'kill "${server:-}" 2>/dev/null || true; rm -rf "$work"' EXIT

expected="six 1.17.0, idna 3.10, docopt 0.6.2, xxh64 894c17e562117b4d, localpkg 0.2.0"
export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv

# Runs a command with no network: in a network namespace of its own where
# the system allows one, and otherwise with every proxy pointing at a closed
# port.
offline() {
  if unshare --user --map-root-user --net true 2>/dev/null; then
    unshare --user --map-root-user --net "$@"
  else
    env HTTP_PROXY=http://127.0.0.1:9 HTTPS_PROXY=http://127.0.0.1:9 ALL_PROXY=http://127.0.0.1:9 \
      http_proxy=http://127.0.0.1:9 https_proxy=http://127.0.0.1:9 all_proxy=http://127.0.0.1:9 "$@"
  fi
}

cp -r "$repo/tests/fixtures/sources" "$work/project"
cd "$work/project"
export PDM_CACHE_DIR="$work/pdm-cache"

echo "== prefetch, then pdm sync, run and build with no network"
pdm-purifier prefetch
rm -rf .venv "$PDM_CACHE_DIR"
offline pdm sync --dev
[ "$(offline pdm run sources 2>/dev/null)" = "$expected" ]
offline pdm build
test -f dist/sources-0.1.0.tar.gz
test -f dist/sources-0.1.0-py3-none-any.whl

echo "== an unlocked dependency fails with pdm-purifier's message"
if offline pdm add certifi 2>"$work/add.log"; then
  echo "adding an unlocked dependency succeeded offline" >&2
  exit 1
fi
grep -q "is not in pdm-purifier.lock.json" "$work/add.log"
grep -q "PDM_PURIFIER_MODE=off" "$work/add.log"
cp "$repo/tests/fixtures/sources/pyproject.toml" "$repo/tests/fixtures/sources/pdm.lock" .

echo "== publish uploads what Nix built"
port=$((20000 + RANDOM % 20000))
python3 "$repo/tests/upload_server.py" "$port" "$work/uploads" &
server=$!
sleep 1
pdm-purifier publish --package sources -- --repository "http://127.0.0.1:$port/" --username test --password test
built=$(readlink -f .pdm-purifier/dist-sources)
for file in sources-0.1.0.tar.gz sources-0.1.0-py3-none-any.whl; do
  cmp "$built/$file" "$work/uploads/$file"
done

echo "== a project changed since the prefetch runs PDM the usual way"
echo "# changed" >>pyproject.toml
# `pdm show` of a package the project does not have queries the index,
# which goes online; the network is cut, so only the warning matters.
offline pdm show certifi 2>"$work/stale.log" || true
grep -q "changed since \`pdm-purifier prefetch\`" "$work/stale.log"
cp "$repo/tests/fixtures/sources/pyproject.toml" .

echo "== a lockfile kept outside the project"
rm -rf .venv .pdm-purifier "$PDM_CACHE_DIR"
mkdir "$work/external"
mv pdm-purifier.lock.json "$work/external/"
export PDM_PURIFIER_LOCKFILE="$work/external/pdm-purifier.lock.json"
pdm-purifier prefetch
test -L "$work/external/.pdm-purifier/manifest"
test ! -e .pdm-purifier
rm -rf .venv "$PDM_CACHE_DIR"
offline pdm sync --dev
[ "$(offline pdm run sources 2>/dev/null)" = "$expected" ]

echo "== a pdm.lock kept outside the project"
rm -rf .venv .pdm-purifier "$PDM_CACHE_DIR" "$work/external/.pdm-purifier"
tree_copy=$(cat pdm.lock)
export PDM_PURIFIER_TOOL_LOCKFILE="$work/external/pdm.lock"
export PDM_LOCKFILE="$PDM_PURIFIER_TOOL_LOCKFILE"
pdm-purifier lock
test -f "$work/external/pdm.lock"
[ "$(cat pdm.lock)" = "$tree_copy" ]
pdm-purifier prefetch
rm -rf .venv "$PDM_CACHE_DIR"
offline pdm sync --dev
[ "$(offline pdm run sources 2>/dev/null)" = "$expected" ]
[ "$(cat pdm.lock)" = "$tree_copy" ]

echo "interactive tests passed"
