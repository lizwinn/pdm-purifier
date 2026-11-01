#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# Tests the verbs of the `pdm-purifier` command that run outside the Nix
# sandbox, on a copy of the sources fixture:
#
# - `pdm-purifier pdm sync`, `pdm run` and `pdm build` work offline from the
#   locked files, with an empty PDM cache;
# - adding a dependency that is not locked fails with pdm-purifier's message;
# - a stale pdm-purifier.lock.json makes `pdm-purifier pdm` run PDM the
#   usual way, with a warning;
# - `pdm-purifier publish` uploads exactly the sdist and wheel Nix built, to
#   a local upload endpoint (tests/upload_server.py).
#
# Run it from the repository root with the CLI on PATH, a Python and a C
# compiler (xxhash compiles one), and with the network to package indexes
# blocked if you want to see that nothing reaches them:
#
#   nix shell '.#cli' 'nixpkgs#python3' 'nixpkgs#gcc' 'nixpkgs#git' -c tests/interactive.sh
set -euo pipefail

repo=$(pwd)
work=$(mktemp -d)
trap 'kill "${server:-}" 2>/dev/null || true; rm -rf "$work"' EXIT

cp -r "$repo/tests/fixtures/sources" "$work/project"
cd "$work/project"
export PDM_CACHE_DIR="$work/pdm-cache"
export PDM_CHECK_UPDATE=false
export PDM_VENV_BACKEND=venv

echo "== pdm sync, run and build, offline"
pdm-purifier pdm sync
output=$(pdm-purifier pdm run sources 2>/dev/null)
[ "$output" = "six 1.17.0, idna 3.10, docopt 0.6.2, xxh64 894c17e562117b4d, localpkg 0.2.0" ]
pdm-purifier pdm build
test -f dist/sources-0.1.0.tar.gz
test -f dist/sources-0.1.0-py3-none-any.whl

echo "== an unlocked dependency fails with pdm-purifier's message"
if pdm-purifier pdm add certifi 2>"$work/add.log"; then
  echo "adding an unlocked dependency succeeded offline" >&2
  exit 1
fi
grep -q "is not in pdm-purifier.lock.json" "$work/add.log"
git -C "$repo" show HEAD:tests/fixtures/sources/pyproject.toml >pyproject.toml
git -C "$repo" show HEAD:tests/fixtures/sources/pdm.lock >pdm.lock

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

echo "== a stale lock runs PDM the usual way"
echo "# changed" >>pyproject.toml
pdm-purifier pdm --version 2>"$work/stale.log"
grep -q "missing or out of date" "$work/stale.log"

echo "interactive tests passed"
