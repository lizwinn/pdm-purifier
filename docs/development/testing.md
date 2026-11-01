# Testing

`nix flake check` builds each fixture under `tests/fixtures/` from its
committed lockfiles in the sandbox, with no network, and runs it
(`tests/default.nix`):

- `simple`: a registry wheel (attrs) and a dependency that ships only an
  sdist (docopt), built with the locked setuptools. Its package check
  builds the project's sdist and wheel.
- `sources`: a wheel and an sdist by URL, two git dependencies (docopt at a
  tag, and python-xxhash, whose C extension compiles the sources of its
  xxHash submodule), and a local package by path, which is a second output.
- `vcs`: yoyo-migrations from Mercurial, docutils from Subversion, and
  python-dateutil from Bazaar.

The flake check also checks the formatting of the Nix files with nixfmt.
`nix flake check --all-systems --no-build` evaluates the checks for
aarch64-linux too.

Three scripts run outside the sandbox, each from the repository root:

- `tests/lock-run.sh` runs `pdm-purifier lock` against the network on a
  copy of each fixture, and fails unless it reproduces the committed
  `pdm-purifier.lock.json`.
- `tests/interactive.sh` runs `pdm-purifier pdm sync`, `run` and `build`
  offline on a copy of the sources fixture, with an empty PDM cache. It
  checks that an unlocked dependency fails with pdm-purifier's message,
  that `publish` uploads exactly the files Nix built to a local endpoint
  (`tests/upload_server.py`), and that a stale lock runs PDM the usual way.
- `tests/relock-fixtures.sh` relocks every fixture, after a change to a
  fixture or to the lock format.

CI (`.github/workflows/check.yml`) runs the flake checks, the evaluation for
every system, `tests/lock-run.sh` and `tests/interactive.sh`, on
x86_64-linux and on aarch64-linux.
