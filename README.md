# pdm-purifier

pdm-purifier lets Nix build a [PDM](https://pdm-project.org) project in its
sandbox, offline, from the project's lockfiles. You do not commit generated
Nix files to the project. It is one of the
[nix-purifiers](https://nix-purifiers.github.io), which share a
[contract](https://github.com/nix-purifiers/purifier/blob/main/CONTRACT.md):
the same builder, commands and checks in every ecosystem.

pdm.lock pins every package with the names and hashes of its files, but not
their URLs, and it pins nothing that PDM installs to build a package.
pdm-purifier adds a PDM plugin and a file, `pdm-purifier.lock.json`, that
hold only those two things: the URLs that pdm.lock leaves out, and the
files that building a package installs. Everything else Nix reads from
pdm.lock and pyproject.toml.

## Quickstart

From the directory that holds pdm.lock, record the downloads and fetch them:

```zsh
nix run github:nix-purifiers/pdm-purifier -- lock
nix run github:nix-purifiers/pdm-purifier -- prefetch
```

Commit `pdm-purifier.lock.json`. Then build the project with Nix, in the
project's `flake.nix`:

```nix
{
  inputs.pdm-purifier.url = "github:nix-purifiers/pdm-purifier";
  inputs.nixpkgs.follows = "pdm-purifier/nixpkgs";

  outputs = { nixpkgs, pdm-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
      project = pdm-purifier.lib.pdm-purifier.buildPdmProject {
        inherit pkgs;
        src = ./.;
      };
    in
    {
      # The script `app` of the project, installed with its dependencies.
      packages.${system}.default = project.programs.app;
      # The sdist and wheel of the project, as `pdm build` makes them.
      packages.${system}.dist = project.packages.app;
      # The project's tests, run in the sandbox.
      checks.${system}.tests = project.tests;
    };
}
```

`buildPdmProject` takes `pkgs`, `src` and `fetchers` as every purifier's
builder does. It returns:

- `packages.<name>` for the project and for each local package it depends
  on by path: what `pdm build` makes, with the attributes `sdist` and
  `wheel` naming its two files.
- `tests`, the project's tests in the sandbox, with every locked group
  installed. The command is `pdm run test` when `[tool.pdm.scripts]`
  defines `test`, and `pdm run python -m pytest` otherwise. The argument
  `testCommand` replaces it.
- `release`, the project's own `packages.<name>`, which `publish` uploads.
- `fetches`, the entries of the shared
  [purifier](https://github.com/nix-purifiers/purifier) library that the
  build fetches, for SBOM, license and vulnerability tools.
- `environment`, a virtual environment with the project and the locked
  groups in `groups` (by default `[ "default" ]`) installed, and
  `programs.<script>` for each console and GUI script, for `nix run`.

It also takes `projectDir` (the project inside `src`, when `src` also holds
local packages outside it), `python`, `nativeBuildInputs` and
`buildInputs` (for a C extension's tools and libraries), `testCommand`,
and `lockFile`. A company mirror or credentials go into
`fetchers.fetchurl`, which works the same way in every purifier.

`lib.pdm-purifier.readLock { src, lockFile }` reads both lockfiles into the
shape that every purifier gives, with `entries`, `outputs` and `problems`.

## Everyday loop

After `prefetch`, the loop goes through plain `pdm`:

```zsh
pdm sync
pdm run app
pdm add requests
pdm build
```

The PDM of the `pdm-purifier` package has the plugin. When the project
has a manifest from `prefetch` and its pdm.lock and pyproject.toml have not
changed since, the plugin answers every request PDM makes from the locked
files in the Nix store.

To change dependencies, run PDM with `PDM_PURIFIER_MODE=off` and update
both lockfiles:

```zsh
PDM_PURIFIER_MODE=off pdm add requests
nix run github:nix-purifiers/pdm-purifier -- lock
nix run github:nix-purifiers/pdm-purifier -- prefetch
```

`lock` keeps pdm.lock as it is. It writes pdm.lock only where it is
missing, and brings it up to date with `pdm lock --update-reuse` where
pyproject.toml no longer matches it. To move versions, run
`pdm-purifier update`, or `pdm-purifier update <package>...` for some
packages. It runs `pdm update --no-sync` and then relocks.

`publish` uploads the `release` that Nix built, with `pdm publish
--no-build`. Arguments after `--` go to `pdm publish`, and `--package
<name>` limits it to some distributions:

```zsh
nix run github:nix-purifiers/pdm-purifier -- publish -- --username __token__ --password "$PYPI_TOKEN"
```

## Offline work

`prefetch` builds the project's manifest with Nix, which fetches every
locked file that installs for the current system and Python. It keeps them
with a garbage-collector root in `.pdm-purifier/` beside the lockfile, and
installs every locked group, the development groups among them, into the
project's virtual environment. Afterwards, `pdm sync`, `pdm run`, `pdm
build` and the editor work with the network cut off.

The tests in `tests/interactive.sh` run these commands in a network
namespace with no interfaces.

## Editor

`prefetch` installs the project into `.venv`, with the development groups.
Point the editor's Python interpreter at `.venv/bin/python`, and its
language server finds every dependency there with no network. A language
server that downloads its own server, such as a Pyright from npm, is not
covered: install it from Nix.

## Errors and fixes

Each refusal names the command that fixes it.

| Message | Cause | Fix |
| --- | --- | --- |
| `pdm-purifier.lock.json does not match pdm.lock and pyproject.toml` | A dependency changed after `lock`. | `pdm-purifier lock` |
| `pdm-purifier.lock.json was changed after pdm-purifier lock wrote it` | Someone edited the file by hand. | `pdm-purifier lock` |
| `pdm-purifier.lock.json has no URL for ...` | pdm.lock lists a file the lockfile has no URL for. | `pdm-purifier lock` |
| `pdm-purifier.lock.json is not valid JSON` | The file is damaged. | Restore it from version control, or `pdm-purifier lock` |
| `<url> is not in pdm-purifier.lock.json` | PDM asked for a file that is not locked. | Run the command with `PDM_PURIFIER_MODE=off`, then `lock` and `prefetch` |
| `pdm.lock or pyproject.toml changed since pdm-purifier prefetch` | The project changed since the last prefetch, so PDM runs online. | `pdm-purifier lock`, then `pdm-purifier prefetch` |

## Sources supported and refused

Supported, as pdm.lock records them:

- packages from the project's indexes and find-links locations, for every
  platform pdm.lock covers;
- files by URL, wheels and sdists;
- local packages by path;
- git repositories, with their submodules, and Mercurial, Subversion and
  Bazaar repositories.

A Mercurial, Subversion or Bazaar checkout from Nix has no `.hg`, `.svn`
or `.bzr` directory. The plugin writes a `PKG-INFO` with the version
pdm.lock pins into such a checkout, so a build that takes its version from
version control history (setuptools-scm, hatch-vcs) gets that version.

Refused:

- a pdm.lock with a hash other than SHA-256, which is not PDM's default;
- a system other than Linux on x86_64 or aarch64, where the wheel tags are
  checked against the package set's glibc.

The lock run builds the project, its local packages, its version control
dependencies and each dependency that has only an sdist for some platform.
A dependency with a C extension needs a C compiler on PATH, as it does for
`pdm install`.

## Examples

[PDM](https://github.com/pdm-project/pdm) 2.27.0, at commit `09c95b78`, is
an example of a real project that CI locks and builds. The CI job
`real-world` (`tests/real-world.sh`) locks it and builds its virtual
environment and its package in the Nix sandbox, and the built `pdm` runs.
The job does not run PDM's own test suite, which runs against PyPI.

Building PDM shows what a larger project asks of the host:

- A package whose sdist builds with a Rust toolchain, such as
  cryptography, cannot be locked from its sdist, because the toolchain
  downloads outside PDM. The lock run skips a package's sdist build when
  wheels for the lock run's Python exist for Linux on x86_64 and on
  aarch64.
- A C extension that builds during the lock run, such as cffi, needs its
  libraries on the host. The job provides libffi and pkg-config.
- When pdm.lock names a file that an index has removed, `pdm-purifier lock`
  stops with a message that says so. The job refreshes pdm.lock with
  `pdm lock` first.

The fixtures under `tests/fixtures/` are smaller examples of the other
sources: a registry wheel with an sdist-only dependency, a mix of URL, git,
local and submodule sources, and a Mercurial, Subversion and Bazaar
dependency.

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo). The shared library
and the contract are in [nix-purifiers/purifier](https://github.com/nix-purifiers/purifier).
`docs/development/` describes the design and the tests.
