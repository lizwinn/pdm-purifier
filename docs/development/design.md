# Design

## One transport under every PDM session

PDM makes every HTTP request through an httpx client that
`BaseEnvironment._build_session` builds: index pages, distribution files,
URL dependencies, and the build requirements it installs for isolated
builds. The plugin (`plugin/src/pdm_purifier/__init__.py`) wraps that
method and gives each client one transport for every URL
(`plugin/src/pdm_purifier/transport.py`). `PDM_PURIFIER_MODE` selects it:

- `record`: the request goes to the transport PDM chose, and each
  distribution file PDM downloads is appended, with its URL and SHA-256, to
  the file `PDM_PURIFIER_RECORD` names.
- `serve`: nothing reaches the network. A locked file comes from the Nix
  store. A request for the index page of a locked project gets a PEP 691
  page that lists only that project's locked files, with their URLs and
  hashes, so PDM resolves to the same files. A find-links location gets an
  HTML page of every locked file. Anything else gets a 404 and a message.

Without the variable the plugin changes nothing, so the PDM of the
`pdm-with-plugin` package behaves like nixpkgs' PDM.

The transport sits under the client, so it serves the project's own
indexes, whatever URLs `pyproject.toml` gives them. PDM's configuration
cannot do that: `pypi.ignore_stored_index` drops the indexes of the
configuration, not those of `pyproject.toml`.

## The lock run

`pdm-purifier lock` runs `pdm purifier lock`, the plugin's command
(`plugin/src/pdm_purifier/lock.py`), in record mode with an empty PDM
cache. It writes `pdm-purifier.lock.json`:

- `artifacts`: download entries of the shared purifier library
  (`path`, `url`, `mirrors`, `hash`), with the project `name`, `version`,
  `file` and `requiresPython` that the served index pages need. They are
  every file of pdm.lock, with the URL that PDM's own finder reports for it
  with platform filtering off, and every file of each version that a build
  downloaded.
- `checkouts`: version control entries of the shared library. A git entry
  pins the plain checkout, and its `commitObject` holds the raw commit
  object and the submodule commits (`gitlinks`) of the commit's tree. A
  Mercurial, Subversion or Bazaar entry pins the checkout that nixpkgs'
  `fetchhg`, `fetchsvn` or `fetchbzr` makes. The lock run gets that hash by
  building the fetcher through the Nix daemon.
- `outputs`: each local distribution (the project, and each package it
  depends on by path) with its name, version, sdist and wheel file names,
  and scripts, read from the build of it.
- `inputsHash`: SHA-256 over pdm.lock and pyproject.toml. The Nix library
  computes the same hash and refuses a stale lockfile.

The builds are what records the build requirements: the project (sdist,
wheel and editable wheel), each local package, each version control
dependency, and each registry or URL dependency with an sdist and no wheel
for every platform. PDM downloads each build's requirements through the
transport. For each version a build downloaded, the lock adds every file of
that version from its index page, so a build on another platform finds its
wheels.

## The Nix build

`nix/lib/build-pdm-project.nix` reads both lockfiles. For each locked
version it takes the wheels that install with the build's Python on the
build's system, or else the sdist. The shared purifier library
(github:nix-purifiers/purifier) decides which wheels install, from the
tags in their file names, and fetches every entry. The builder writes a
manifest of all of them.

Git dependencies are cloned by PDM, so their entries ask the library for a
`.git` directory. The library rebuilds it from the entry's commit object
and gitlinks, and checks that the commit has the locked ID and the tree
of the checkout. Git's
`url.<path>.insteadOf` sends each clone, and each submodule clone, to its
rebuilt repository. The plugin copies a Mercurial, Subversion or Bazaar
checkout in place of unearth's clone, reports its locked revision, and
writes a `PKG-INFO` with the locked version, which setuptools-scm reads
when there is no version control metadata.

PDM then runs in serve mode: `pdm sync --prod --no-editable` into a
virtual environment for `environment`, and `pdm build` for each
`packages.<name>`.

## The command

`pdm-purifier pdm` builds the manifest with Nix (`nix/lib/cli.nix`), keeps
it alive with a GC root in `.pdm-purifier/`, and runs PDM in serve mode.
`publish` builds a distribution with Nix and runs `pdm publish --no-build`
on what Nix built.
