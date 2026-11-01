# pdm-purifier

pdm-purifier lets Nix build a [PDM](https://pdm-project.org) project in its
sandbox, offline, from the project's lockfiles. You do not commit generated
Nix files to the project.

pdm.lock pins every package with the names and hashes of its files, but not
their URLs, and it pins nothing that PDM installs to build a package. A PDM
plugin fills that gap. `pdm-purifier lock` runs every build that installing
the project can need, and records each file PDM downloads, together with
the URL of every file in pdm.lock, in `pdm-purifier.lock.json`. In the Nix
build, and in `pdm-purifier pdm`, the plugin answers every request PDM makes
from the locked files, so PDM installs and builds with no network.

## Lock

From the directory that holds pdm.lock:

```zsh
nix run github:nix-purifiers/pdm-purifier -- lock
```

Commit `pdm-purifier.lock.json`. Run it again after `pdm lock` changes
pdm.lock, or after a change to pyproject.toml. The Nix build refuses a
`pdm-purifier.lock.json` that no longer matches them.

The lock run builds the project, its local packages, its version control
dependencies, and each dependency that has only an sdist for some platform.
A dependency with a C extension needs a C compiler on PATH, and its system
libraries, as it does for `pdm install`.

## Build

The flake's `overlays.default` adds `buildPdmProject` to a package set:

```nix
{
  inputs.pdm-purifier.url = "github:nix-purifiers/pdm-purifier";
  inputs.nixpkgs.follows = "pdm-purifier/nixpkgs";

  outputs = { nixpkgs, pdm-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ pdm-purifier.overlays.default ];
      };
      project = pkgs.buildPdmProject { src = ./.; };
    in
    {
      # The script `app` of the project, installed with its dependencies.
      packages.${system}.default = project.programs.app;
      # A virtual environment with the project and its dependencies.
      packages.${system}.environment = project.environment;
      # The sdist and wheel of the project, as `pdm build` makes them.
      packages.${system}.dist = project.packages.app;
    };
}
```

`buildPdmProject` gives:

- `environment`, a virtual environment with the project and the locked
  groups in `groups` (by default `[ "default" ]`) installed, and the
  project's scripts in `bin/`.
- `packages.<name>` for the project and for each local package it depends
  on by path: what `pdm build` makes, with the attributes `sdist` and
  `wheel` naming its two files.
- `programs.<script>` for each console and GUI script of the project and
  its local packages, for `nix run`.

The project's distributions, their versions, file names and scripts are
recorded by the lock run, so Nix knows every output when it evaluates, with
no import from derivation.

`buildPdmProject` also takes:

- `projectDir`, the project inside `src`, when `src` must also hold local
  packages outside the project directory, such as `../shared`.
- `python` (default `python3`), which must satisfy the project's
  `requires-python`.
- `nativeBuildInputs` and `buildInputs`, for the tools and system libraries
  that building a C extension needs.
- `fetchurl`, a replacement for nixpkgs' `fetchurl`, for credentials or
  mirrors. The shared [purifier](https://github.com/nix-purifiers/purifier)
  library calls it with the arguments it passes to nixpkgs' `fetchurl`.

## PDM offline

```zsh
nix run github:nix-purifiers/pdm-purifier -- pdm sync
```

`pdm-purifier pdm` runs PDM with its arguments, serving it the locked files
from the Nix store. `pdm sync`, `pdm install`, `pdm run` and `pdm build`
then work with no network. A request for anything that is not locked fails
with a message. Change dependencies with plain `pdm` (`pdm add`, `pdm
lock`), then run `pdm-purifier lock`. When `pdm-purifier.lock.json` is
missing or out of date, `pdm-purifier pdm` warns and runs PDM the usual way.

`nix develop github:nix-purifiers/pdm-purifier` gives a shell with the PDM
that the Nix build runs, which has the plugin, and the `pdm-purifier`
command.

## Publish

```zsh
nix run github:nix-purifiers/pdm-purifier -- publish -- --username __token__ --password "$PYPI_TOKEN"
```

`publish` builds each local distribution with Nix and uploads what Nix
built with `pdm publish --no-build`. Arguments after `--` go to `pdm
publish`. `--package <name>` limits it to some distributions.

## Dependencies

pdm-purifier supports every source pdm.lock records:

- packages from the project's indexes and find-links locations, for every
  platform the lock covers;
- files by URL, wheels and sdists;
- local packages by path;
- git repositories, with their submodules, and Mercurial, Subversion and
  Bazaar repositories.

A Mercurial, Subversion or Bazaar checkout from Nix has no `.hg`, `.svn`
or `.bzr` directory. The plugin writes a `PKG-INFO` with the version
pdm.lock pins into such a checkout, so a build that takes its version from
version control history (setuptools-scm, hatch-vcs) gets that version.

## Limits

- The build runs on Linux (x86_64 and aarch64), where the wheel tags are
  checked against the package set's glibc.
- pdm.lock must use SHA-256 file hashes, which is PDM's default.

`docs/development/` describes the design and the tests.

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
