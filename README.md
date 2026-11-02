# pdm-purifier

pdm-purifier keeps PDM's development workflow on locked,
Nix-resolved dependencies. Use the normal build and test commands in your
working tree; building the project itself in the Nix sandbox is an
optional next step.

pdm.lock pins every package with the names and hashes of its files, but not
their URLs, and it pins nothing that PDM installs to build a package.
pdm-purifier adds a PDM plugin and a file, `pdm-purifier.lock.json`, that
hold only those two things: the URLs that pdm.lock leaves out, and the
files that building a package installs. Nix reads everything else from
pdm.lock and pyproject.toml.

## Quickstart

From the project root:

```zsh
nix shell 'github:nix-purifiers/pdm-purifier'
pdm-purifier lock
pdm-purifier prefetch
eval "$(pdm venv activate)"
pytest
```

`prefetch` installs into PDM’s virtual environment. `pdm venv activate`
activates it using PDM’s environment settings.

Commit the lockfiles that the lock command writes, including the build
tool's own lockfile when it has one. Keep using the project's usual build,
test and editor commands with this setup. Nix provides the locked
dependencies; the development commands above run outside the Nix sandbox.
No project Nix files are needed for this workflow.

Sandboxed builds of the whole project are an optional
[next step](#building-the-project-with-nix).

The shell provides the `pdm` wrapper. Use it for the locked
development workflow. With no purifier lockfile, it warns on standard
error and runs the ordinary tool with impure resolution.

For persistent use, add these packages through your usual Nix configuration.


## Development loop

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
nix shell 'github:nix-purifiers/pdm-purifier'
PDM_PURIFIER_MODE=off pdm add requests
pdm-purifier lock
pdm-purifier prefetch
```

`lock` keeps the versions in pdm.lock. It writes pdm.lock where it is
missing, and brings it up to date with `pdm lock --update-reuse` where
pyproject.toml no longer matches it. To move versions, run
`pdm-purifier update`, or `pdm-purifier update <package>...` for some
packages. It runs `pdm update --no-sync` and then relocks.

`publish` uploads the `release` that Nix built, with `pdm publish
--no-build`. Arguments after `--` go to `pdm publish`, and `--package <name>` limits it to some distributions:

```zsh
nix shell 'github:nix-purifiers/pdm-purifier'
pdm-purifier publish -- \
  --username __token__ --password "$PYPI_TOKEN"
```

A project can keep its build external, in the repository of the flake that
calls the builder. That flake passes `lockFile` and `pdmLock` to
`buildPdmProject`, and the builder uses them in place of the copies in
`src`. Every command takes `--lockfile <path>`, or reads
`PDM_PURIFIER_LOCKFILE`, for `pdm-purifier.lock.json`, and
`--tool-lockfile <path>`, or reads `PDM_PURIFIER_TOOL_LOCKFILE`, for
`pdm.lock`. With either one, `lock` and `update` write the file there and
leave the copy in the project as it is, and `lock` starts from the copy in
the project when the outside one does not exist yet. The dev shell of the
flake can set `PDM_PURIFIER_LOCKFILE` and `PDM_PURIFIER_TOOL_LOCKFILE`, and
`PDM_LOCKFILE` to the same path as the second, which plain `pdm` reads.

## Published plugin

Versioned plugin wheels are available in the [package index](https://nix-purifiers.github.io/pdm-purifier/simple/pdm-purifier/)
and as [release assets](https://github.com/nix-purifiers/pdm-purifier/releases).
Install a wheel URL with `pdm self add WHEEL_URL`.
Use `pdm-purifier lock` and `pdm-purifier prefetch` from the Quickstart to
prepare the project; the plugin then serves its locked dependencies to PDM.

## Dependencies from another purified project

```zsh
nix shell 'github:nix-purifiers/pdm-purifier'
pdm-purifier lock \
  --input 'github:owner/library/<rev>#library'
pdm-purifier prefetch
pdm sync
pdm run test
```

The producer must expose `projections.python`. The plugin applies its wheels
through PDM's native resolver overrides; project dependency declarations stay
unchanged. The purifier lock records the pinned Nix source and omits supplied
wheels from its downloads. Relocking retains that pin; `update` refreshes it.
Repeat `--input` for additional producers. Conflicting providers are rejected.

After prefetch, plain PDM commands use the bindings from the Nix-built
manifest. Recorded wheel paths are rebound for the current machine without
rewriting committed lockfiles. Supplied wheels bypass writable wheel and
installation caches.

The builder exposes `projections.python` on each local package and on the
whole project. Each wheelhouse follows the package's native runtime graph;
unrelated development and build tools are excluded. Composed publishing
uploads those wheels and their runtime closure, with Nix-derived versions and
dependency metadata for ordinary installers. Use an index accepting local
versions, or consume the wheelhouse with `--find-links`.

## Building the project with Nix

Once the native development workflow is working, you can also build and
test the whole project in the Nix sandbox. For this step, keep a flake or
another Nix build definition in the project's repository, or maintain an
external packaging repository that points at its sources and lockfiles.
The builder consumes the same lockfiles as the development workflow.

The result is the sdist and wheel of the project `app`, as `pdm build` makes
them. A project whose authors want a flake can have one that packages it.
The flake calls the builder directly, and it can live in the project's
repository or in another one:

```nix
{
  inputs.pdm-purifier.url =
    "github:nix-purifiers/pdm-purifier";
  inputs.nixpkgs.follows = "pdm-purifier/nixpkgs";

  outputs =
    { nixpkgs, pdm-purifier, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs {
        inherit system;
        overlays = [ pdm-purifier.overlays.default ];
      };
      project = pkgs.pdm-purifier.buildPdmProject {
        src = ./.;
      };
    in
    {
      packages.${system} = {
        # The script `app` of the project, installed
        # with its dependencies.
        default = project.programs.app;
        # The sdist and wheel of the project, as `pdm
        # build` makes them.
        dist = project.packages.app;
      };
      # The project's tests, run in the sandbox.
      checks.${system}.tests = project.tests;
    };
}
```

`buildPdmProject` is a package for `callPackage` in the scope. It takes the
packages it needs by name, and `buildPdmProject.override` replaces any of
them. `pdm-purifier.overrideScope` replaces what everything in the scope
shares. Its own arguments are `src`; `lockFile`, which defaults to
`pdm-purifier.lock.json` in the project; `pdmLock`, which defaults to
`pdm.lock` in the project; and `fetchers`, whose `fetchurl` takes a company
mirror or credentials and works the same way in every purifier. It
returns:

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

The builder also takes `projectDir` (the project inside `src`, when `src`
also holds local packages outside it), `python`, `nativeBuildInputs` and
`buildInputs` (for a C extension's tools and libraries), and `testCommand`.
The argument `env` sets environment variables for the builds. A project that
takes its version from git sets `PDM_BUILD_SCM_VERSION` in it, because the
source of a flake has no `.git` directory.

`lib.pdm-purifier.readLock { src, lockFile, pdmLock }` reads both lockfiles
into the shape that every purifier gives, with `entries`, `outputs` and
`problems`.

### One-off builds without a project Nix file

For an ad hoc build, the builder can also be evaluated directly from the
project root. Replace the example package name with one from your project:

```zsh
nix build --impure --expr 'let
  purifier = builtins.getFlake "github:nix-purifiers/pdm-purifier";
  pkgs = import purifier.inputs.nixpkgs {
    system = builtins.currentSystem;
    overlays = [ purifier.overlays.default ];
  };
in
(pkgs.pdm-purifier.buildPdmProject { src = ./.; }).packages.app'
```

This uses the purifier's pinned nixpkgs, matching the lock command above.
To build with ambient `<nixpkgs>` from your Nix search path instead,
replace `import purifier.inputs.nixpkgs` with `import <nixpkgs>`.
Both forms need no Nix files in your project. The build tool and language
versions must match the lockfile; with ambient nixpkgs, lock with the
purifier from that package set or pass a compatible toolchain to the builder.

## Working offline

`prefetch` builds the project's manifest with Nix, which fetches every
locked file that installs for the current system and Python. It keeps them
with a garbage-collector root in `.pdm-purifier/` beside the lockfile, and
installs every locked group, the development groups among them, into the
project's virtual environment. Afterwards, `pdm sync`, `pdm run`, `pdm
build` and the editor work with the network cut off.

## Editor

`prefetch` installs the project into `.venv`, with the development groups.
Point the editor's Python interpreter at `.venv/bin/python`, and its
language server finds every dependency there with no network. Install the
language server itself from Nix.

## Troubleshooting

Each message names the command that fixes it.

| Message | Cause | Fix |
| --- | --- | --- |
| `pdm-purifier.lock.json does not match pdm.lock and pyproject.toml` | A dependency changed after `lock`. | `pdm-purifier lock` |
| `pdm-purifier.lock.json was changed after pdm-purifier lock wrote it` | Someone edited the file by hand. | `pdm-purifier lock` |
| `pdm-purifier.lock.json has no URL for ...` | pdm.lock lists a file the lockfile has no URL for. | `pdm-purifier lock` |
| `pdm-purifier.lock.json is not valid JSON` | The file is damaged. | Restore it from version control, or `pdm-purifier lock` |
| `<url> is not in pdm-purifier.lock.json` | PDM asked for a file that is not locked. | Run the command with `PDM_PURIFIER_MODE=off`, then `lock` and `prefetch` |
| `pdm.lock or pyproject.toml changed since pdm-purifier prefetch` | The project changed since the last prefetch, so PDM stops until the lock and cache are renewed. | `pdm-purifier lock`, then `pdm-purifier prefetch` |

## Supported language repositories

pdm-purifier builds every source pdm.lock records:

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

The build runs on Linux for x86_64 and aarch64, where the wheel tags are
checked against the package set's glibc. pdm.lock must use SHA-256 file
hashes, which is PDM's default.

pdm.lock does not record the system that a file is for, so the entries of
the lock carry no `systems`. For each locked version, the builder fetches
the wheels whose file names show that they install with its Python on its
system, or else the sdist.

The lock run builds the project, its local packages, its version control
dependencies, and each dependency that has no wheel for Linux on x86_64 or
on aarch64 with the lock run's Python. A dependency with a C extension
needs a C compiler on PATH, as it does for `pdm install`.

## Examples

For day-to-day work on these projects, use the native-tool setup and
commands in [Quickstart](#quickstart) and [Development loop](#development-loop).
The Nix expressions below show optional sandboxed packaging of those
projects.

To build [PDM](https://github.com/pdm-project/pdm) itself with Nix, clone
it, bring its pdm.lock up to date, and lock the downloads:

```zsh
nix shell 'github:nix-purifiers/pdm-purifier'
git clone https://github.com/pdm-project/pdm
cd pdm
pdm lock -G :all
pdm-purifier lock
```

Then build it from the directory of the clone:

```zsh
nix build --impure --expr 'let
  purifier = builtins.getFlake "github:nix-purifiers/pdm-purifier";
  pkgs = import purifier.inputs.nixpkgs {
    system = builtins.currentSystem;
    overlays = [ purifier.overlays.default ];
  };
in
(pkgs.pdm-purifier.buildPdmProject { src = ./.; }).packages.pdm'
```

The result holds the sdist and the wheel of PDM. To get the `pdm` command
that the build installs, take `programs.pdm` from the same expression and
start it from the `result` link:

```zsh
nix build --impure --expr 'let
  purifier = builtins.getFlake "github:nix-purifiers/pdm-purifier";
  pkgs = import purifier.inputs.nixpkgs {
    system = builtins.currentSystem;
    overlays = [ purifier.overlays.default ];
  };
in
(pkgs.pdm-purifier.buildPdmProject { src = ./.; }).programs.pdm'
result/bin/pdm --version
```

## Credits

The purifier idea was inspired by nixcloud's
[cargo (libnix)](https://github.com/nixcloud/cargo).
