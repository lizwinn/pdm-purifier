# SPDX-License-Identifier: MIT
#
# The checks of `nix flake check`. Each fixture under fixtures/ is a PDM
# project with a committed pdm.lock and pdm-purifier.lock.json
# (relock-fixtures.sh makes both). The checks build each fixture from its
# lockfiles in the sandbox, with no network, and run what it built.
{
  pkgs,
  overlay,
  cli,
}:
let
  final = pkgs.extend overlay;
  inherit (final) lib runCommand;

  # A fixture directory as Nix copies it, without what PDM leaves behind.
  fixture =
    name:
    lib.fileset.toSource {
      root = ./fixtures + "/${name}";
      fileset = lib.fileset.difference (./fixtures + "/${name}") (
        lib.fileset.unions (
          map (p: lib.fileset.maybeMissing (./fixtures + "/${name}/${p}")) [
            ".venv"
            ".pdm-python"
            ".pdm-build"
            ".pdm-purifier"
            "dist"
          ]
        )
      );
    };

  simple = final.buildPdmProject { src = fixture "simple"; };
  sources = final.buildPdmProject { src = fixture "sources"; };
  vcs = final.buildPdmProject { src = fixture "vcs"; };
  # The version the vcs fixture's pdm.lock pins for a package.
  vcsVersion =
    name:
    (lib.findFirst (p: p.name == name) (throw "fixtures/vcs/pdm.lock has no ${name}")
      (builtins.fromTOML (builtins.readFile ./fixtures/vcs/pdm.lock)).package
    ).version;
in
{
  inherit cli;

  # The project and its dependencies install from the lockfiles: attrs from
  # its wheel, and docopt from its sdist, built with the locked setuptools.
  simple-runs = runCommand "simple-runs" { } ''
    output=$(${lib.getExe simple.programs.simple} World)
    echo "$output"
    [ "$output" = "Hello, World, from simple" ]
    touch $out
  '';

  # `pdm build` makes the sdist and the wheel that the lock run recorded.
  simple-package = runCommand "simple-package" { } ''
    test -f ${simple.packages.simple.sdist}
    test -f ${simple.packages.simple.wheel}
    ${final.unzip}/bin/unzip -l ${simple.packages.simple.wheel} | grep -q 'simple/__init__.py'
    touch $out
  '';

  # A wheel by URL, an sdist by URL built with the locked flit_core, two git
  # dependencies cloned from their locked checkouts and built with the
  # locked setuptools (xxhash with its submodule, whose C sources its
  # extension compiles), and a local package by path.
  sources-runs = runCommand "sources-runs" { } ''
    output=$(${lib.getExe sources.programs.sources})
    echo "$output"
    [ "$output" = "six 1.17.0, idna 3.10, docopt 0.6.2, xxh64 894c17e562117b4d, localpkg 0.2.0" ]
    [ "$(${lib.getExe sources.programs.localpkg})" = "localpkg 0.2.0" ]
    touch $out
  '';

  # A Mercurial, a Subversion and a Bazaar dependency, which the plugin
  # copies from their locked checkouts in place of a clone, built with their
  # locked build requirements.
  vcs-runs = runCommand "vcs-runs" { } ''
    output=$(${lib.getExe vcs.programs.vcs})
    echo "$output"
    [ "$output" = "yoyo-migrations ${vcsVersion "yoyo-migrations"} (yoyo), docutils ${vcsVersion "docutils"} (docutils), python-dateutil ${vcsVersion "python-dateutil"} (dateutil)" ]
    touch $out
  '';

  # The local package is an output of its own.
  sources-local-package = runCommand "sources-local-package" { } ''
    test -f ${sources.packages.localpkg.sdist}
    test -f ${sources.packages.localpkg.wheel}
    touch $out
  '';
}
