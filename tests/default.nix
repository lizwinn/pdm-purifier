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

  # The simple fixture's pdm-purifier.lock.json, changed by `edit`, as a
  # file of its own.
  simpleLock = builtins.fromJSON (builtins.readFile ./fixtures/simple/pdm-purifier.lock.json);
  editedLock = name: edit: builtins.toFile "${name}.json" (builtins.toJSON (edit simpleLock));

  # Whether reading the simple fixture with `lockFile` fails when Nix
  # evaluates it, as each broken lockfile must.
  refusedAtEvaluation =
    lockFile:
    !(builtins.tryEval (
      builtins.deepSeq
        (final.buildPdmProject {
          src = fixture "simple";
          inherit lockFile;
        }).packages
        true
    )).success;

  # A build of the simple fixture that must fail, with the log of the
  # failure in $out/testBuildFailure.log.
  failedBuild = project: final.testers.testBuildFailure project.environment;
in
{
  inherit cli;

  # The unit tests of the plugin's transports and lock helpers, and of the
  # command (tests/unit/).
  unit =
    runCommand "unit-tests"
      {
        nativeBuildInputs = [
          (final.python3.withPackages (ps: [
            ps.httpx
            ps.packaging
          ]))
        ];
      }
      ''
        export PYTHONPATH=${../plugin/src}:${../cli}
        python3 -m unittest discover --start-directory ${./unit} --verbose
        touch $out
      '';

  # Lockfiles the Nix library refuses with a message: one that no longer
  # matches pdm.lock and pyproject.toml, one of another format version, one
  # that is not an object, and one that is missing.
  refuses-broken-lockfiles =
    assert refusedAtEvaluation (editedLock "stale" (lock: lock // { inputsHash = "0"; }));
    assert refusedAtEvaluation (editedLock "version" (lock: lock // { version = 0; }));
    assert refusedAtEvaluation (builtins.toFile "shape.json" "[]");
    assert refusedAtEvaluation (./fixtures/simple + "/missing.json");
    runCommand "refuses-broken-lockfiles" { } "touch $out";

  # A lockfile without attrs' wheel: PDM asks for it, and the plugin refuses
  # it with a message instead of reaching the network.
  refuses-missing-entry =
    let
      failure = failedBuild (
        final.buildPdmProject {
          src = fixture "simple";
          lockFile = editedLock "missing-entry" (
            lock:
            lock
            // {
              artifacts = builtins.filter (entry: !(lib.hasPrefix "attrs-" entry.file)) lock.artifacts;
            }
          );
        }
      );
    in
    runCommand "refuses-missing-entry" { } ''
      grep -q "is not in pdm-purifier.lock.json" ${failure}/testBuildFailure.log
      touch $out
    '';

  # A pdm.lock whose hash of attrs' wheel was edited: PDM refuses the wheel
  # the plugin serves, because it does not have the hash pdm.lock names
  # (negative/tampered-hash, from make-negative-fixtures.py).
  refuses-tampered-hash =
    let
      failure = failedBuild (final.buildPdmProject { src = ./negative/tampered-hash; });
    in
    runCommand "refuses-tampered-hash" { } ''
      grep -qi "hash" ${failure}/testBuildFailure.log
      grep -q "attrs" ${failure}/testBuildFailure.log
      touch $out
    '';

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
