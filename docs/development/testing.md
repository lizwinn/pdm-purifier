# Testing

`nix flake check` builds each fixture under `tests/fixtures/` from its
committed lockfiles in the sandbox, with no network, and runs it
(`tests/default.nix`):

- `simple`: a registry wheel (attrs), a dependency that ships only an sdist
  (docopt), built with the locked setuptools, and a `test` group with
  pytest. Its checks run the script, run the project's tests in the
  sandbox (`simple.tests`), and build the project's sdist and wheel.
- `sources`: a wheel and an sdist by URL, two git dependencies (docopt at a
  tag, and python-xxhash, whose C extension compiles the sources of its
  xxHash submodule), and a local package by path, which is a second output.
- `vcs`: yoyo-migrations from Mercurial, docutils from Subversion, and
  python-dateutil from Bazaar.
- `update`: six pinned at 1.15.0 while pyproject.toml allows `six>=1.15`,
  for `pdm-purifier update`.

The flake check also runs the checks of the purifier contract
(CONTRACT.md in github:nix-purifiers/purifier), each named
`conformance-*`, and the unit tests:

- `unit` runs the unit tests in `tests/unit/`. They cover the transports
  (serving locked files, index and find-links pages, refusing everything
  else, recording distribution files, and choosing serve mode for a
  prefetched project), the helpers of the lock run (file names, hashes and
  `PKG-INFO`), and the command (where it looks for the lockfile, stale and
  malformed lockfiles, local distributions, and the source root of local
  packages).
- `conformance-stale` checks that a lockfile older than pdm.lock and
  pyproject.toml is refused with a message that names `pdm-purifier lock`,
  both by `readLock` and by the builder.
- `conformance-tampered` checks that a lockfile with an edited URL or hash
  is refused by its content hash.
- `conformance-missing` checks that a lockfile without a file that building
  docopt's sdist installs fails the build with a message that names
  `pdm-purifier lock`, and that a lockfile without the URL of a file
  pdm.lock lists, without a field, or missing altogether is refused at
  evaluation.
- `conformance-malformed` checks that a lockfile that is not an object, or
  of another format version, is refused.
- `conformance-rebuild` checks that a second build of the simple fixture's
  package gives the same sdist and wheel.
- `conformance-offline` copies the simple fixture, gives it the manifest
  that `pdm-purifier prefetch` keeps, and runs plain `pdm sync`, `pdm run`,
  the project's tests and `pdm build` in the sandbox, with no network.
- `conformance-external` builds the simple fixture with its
  `pdm-purifier.lock.json` outside `src`.
- `conformance-update` checks the update fixture's starting point. The
  update itself needs the network, so it is a CI job.

`conformance-relock` and `conformance-update` need the network, and run in
CI as jobs of the same name.

The flake check also checks the formatting of the Nix files with nixfmt.
`nix flake check --all-systems --no-build` evaluates the checks for
aarch64-linux too.

Three scripts run outside the sandbox, each from the repository root:

- `tests/lock-run.sh` (`conformance-relock`) runs `pdm-purifier lock`
  against the network on a copy of each fixture, and fails unless it
  reproduces the committed `pdm-purifier.lock.json`.
- `tests/update.sh` (`conformance-update`) runs `pdm-purifier update` on a
  copy of the update fixture, checks that six moved from 1.15.0, and checks
  that `pdm lock --check` and `pdm-purifier prefetch` then pass.
- `tests/interactive.sh` (`conformance-offline`) runs `pdm-purifier
  prefetch` on a copy of the sources fixture, and then plain `pdm sync`,
  `run` and `build` in a network namespace with no interfaces and an empty
  PDM cache. It checks that an unlocked dependency fails with the plugin's
  message, that a project changed since the prefetch runs PDM the usual
  way, that a lockfile kept outside the project works the same, and that
  `publish` uploads exactly the files Nix built to a local endpoint
  (`tests/upload_server.py`).

`tests/relock-fixtures.sh` relocks every fixture, after a change to a
fixture or to the lock format.

CI (`.github/workflows/check.yml`) runs the flake checks, the evaluation
for every system, and the three jobs above, on x86_64-linux and on
aarch64-linux.
