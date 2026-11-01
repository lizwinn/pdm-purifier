# SPDX-License-Identifier: MIT
#
# The checks of `nix flake check`. Each fixture under fixtures/ is a PDM
# project with a committed pdm.lock and pdm-purifier.lock.json
# (relock-fixtures.sh makes both). The checks build each fixture from its
# lockfiles in the sandbox, with no network, and run what it built.
#
# The `conformance-*` checks are those of the purifier contract (CONTRACT.md
# in github:nix-purifiers/purifier). `conformance-relock` needs the network,
# so it is a CI job of that name (lock-run.sh) and has no check here.
{
  pkgs,
  # overlays.default and lib.pdm-purifier.readLock of this flake.
  overlay,
  readLock,
  cli,
}:
let
  inherit (pkgs) lib runCommand;
  inherit (builtins) hashString removeAttrs toJSON;

  # A fixture directory as Nix copies it, without what PDM leaves behind,
  # and without the files in `drop`.
  fixtureWithout =
    drop: name:
    lib.fileset.toSource {
      root = ./fixtures + "/${name}";
      fileset = lib.fileset.difference (./fixtures + "/${name}") (
        lib.fileset.unions (
          map (p: lib.fileset.maybeMissing (./fixtures + "/${name}/${p}")) (
            [
              ".venv"
              ".pdm-python"
              ".pdm-build"
              ".pdm-purifier"
              "dist"
            ]
            ++ drop
          )
        )
      );
    };
  fixture = fixtureWithout [ ];

  build = (pkgs.extend overlay).buildPdmProject;

  simple = build { src = fixture "simple"; };
  sources = build { src = fixture "sources"; };
  vcs = build { src = fixture "vcs"; };
  # The version the vcs fixture's pdm.lock pins for a package.
  vcsVersion =
    name:
    (lib.findFirst (p: p.name == name) (throw "fixtures/vcs/pdm.lock has no ${name}")
      (builtins.fromTOML (builtins.readFile ./fixtures/vcs/pdm.lock)).package
    ).version;

  # The simple fixture's pdm-purifier.lock.json, changed by `edit`, as a
  # file of its own. `editedLock` recomputes the contentHash, as a relock
  # would; `tamperedLock` keeps the old one, as a hand edit would.
  simpleLock = builtins.fromJSON (builtins.readFile ./fixtures/simple/pdm-purifier.lock.json);
  rehash =
    lock: lock // { contentHash = hashString "sha256" (toJSON (removeAttrs lock [ "contentHash" ])); };
  editedLock = name: edit: builtins.toFile "${name}.json" (toJSON (rehash (edit simpleLock)));
  tamperedLock = name: edit: builtins.toFile "${name}.json" (toJSON (edit simpleLock));

  # The problem readLock finds when it reads the simple fixture with the
  # lockfile at `lockFile`, or null when it finds none.
  refusal =
    lockFile:
    let
      problems =
        (readLock {
          src = fixture "simple";
          inherit lockFile;
        }).problems;
    in
    if problems == [ ] then null else builtins.head problems;

  # A check that each lockfile is refused with a message naming the command
  # that fixes it, and that the builder refuses it too.
  refusedNamingTheFix =
    name: lockFiles:
    assert lib.all (
      lockFile:
      let
        message = refusal lockFile;
      in
      lib.assertMsg (
        message != null && lib.hasInfix "pdm-purifier lock" message
      ) "${name}: ${toString lockFile} was not refused with a message naming `pdm-purifier lock`"
      && lib.assertMsg (
        !(builtins.tryEval (
          builtins.deepSeq
            (build {
              src = fixture "simple";
              inherit lockFile;
            }).packages
            true
        )).success
      ) "${name}: the builder accepted ${toString lockFile}"
    ) lockFiles;
    runCommand name { } "touch $out";

  # A build that must fail, with the log of the failure in
  # $out/testBuildFailure.log.
  failedBuild = drv: pkgs.testers.testBuildFailure drv;
in
{
  inherit cli;

  # The unit tests of the plugin's transports and lock helpers, and of the
  # command (tests/unit/).
  unit =
    runCommand "unit-tests"
      {
        nativeBuildInputs = [
          (pkgs.python3.withPackages (ps: [
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

  # A lockfile that no longer matches pdm.lock and pyproject.toml.
  conformance-stale = refusedNamingTheFix "conformance-stale" [
    (editedLock "stale" (lock: lock // { inputsHash = "0"; }))
  ];

  # A lockfile whose URL of attrs' wheel, or whose hash of a build
  # requirement, was edited by hand is refused at evaluation, by its
  # contentHash. The hashes of the files pdm.lock lists are pdm.lock's own,
  # which Nix fetches each file with, so an edited one fails that
  # fixed-output fetch.
  conformance-tampered = refusedNamingTheFix "conformance-tampered" [
    (tamperedLock "tampered-url" (
      lock:
      lock
      // {
        urls = lib.mapAttrs (
          file: url: if lib.hasPrefix "attrs-" file then "https://example.org/${file}" else url
        ) lock.urls;
      }
    ))
    (tamperedLock "tampered-hash" (
      lock:
      lock
      // {
        buildRequirements = map (
          entry: entry // { hash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="; }
        ) lock.buildRequirements;
      }
    ))
  ];

  # A lockfile without the setuptools that building docopt's sdist
  # installs: PDM asks for it, and the plugin refuses it with a message
  # naming `pdm-purifier lock`, instead of reaching the network. A lockfile
  # without the URL of attrs' wheel, which pdm.lock lists, one without one
  # of its fields, and a missing lockfile are refused at evaluation.
  conformance-missing =
    let
      failure =
        failedBuild
          (build {
            src = fixture "simple";
            lockFile = editedLock "missing-entry" (
              lock:
              lock
              // {
                buildRequirements = builtins.filter (entry: entry.name != "setuptools") lock.buildRequirements;
              }
            );
          }).environment;
      refused = refusedNamingTheFix "conformance-missing-refusals" [
        (editedLock "missing-url" (
          lock: lock // { urls = lib.filterAttrs (file: _: !(lib.hasPrefix "attrs-" file)) lock.urls; }
        ))
        (editedLock "missing-field" (lock: removeAttrs lock [ "checkouts" ]))
        (./fixtures/simple + "/missing.json")
      ];
    in
    runCommand "conformance-missing" { } ''
      : ${refused}
      grep -q "is not in pdm-purifier.lock.json" ${failure}/testBuildFailure.log
      grep -q "pdm-purifier lock" ${failure}/testBuildFailure.log
      touch $out
    '';

  # A lockfile that is not an object, and one of another format version. A
  # file that is not JSON fails in Nix's own JSON parser, whose error the
  # library gives the message as context; the command's unit tests check
  # its own message for it.
  conformance-malformed = refusedNamingTheFix "conformance-malformed" [
    (builtins.toFile "shape.json" "[]")
    (editedLock "version" (lock: lock // { version = 0; }))
  ];

  # Building the simple fixture's package a second time gives the same
  # sdist and wheel, byte for byte.
  conformance-rebuild =
    let
      first = simple.packages.simple;
      second = first.overrideAttrs { REBUILD = "second"; };
    in
    runCommand "conformance-rebuild" { } ''
      diff -r ${first} ${second}
      touch $out
    '';

  # The development loop of a prefetched project, with no network: the
  # project has the manifest that `pdm-purifier prefetch` keeps, and plain
  # `pdm` (with the plugin, and no PDM_PURIFIER_MODE) installs every
  # group, runs the project and its tests, and builds it.
  conformance-offline =
    runCommand "conformance-offline"
      {
        nativeBuildInputs = [
          cli
          pkgs.git
          pkgs.python3
        ];
      }
      ''
        export HOME="$TMPDIR/home" PDM_CHECK_UPDATE=false PDM_VENV_BACKEND=venv
        cp -r ${fixture "simple"} project
        chmod -R u+w project
        cd project
        mkdir .pdm-purifier
        ln -s ${simple.manifest} .pdm-purifier/manifest
        sha256sum <(cat pdm.lock pyproject.toml) | cut -d' ' -f1 > .pdm-purifier/inputs
        pdm sync --dev
        [ "$(pdm run simple World)" = "Hello, World, from simple" ]
        pdm run python -m pytest
        pdm build
        test -f dist/simple-0.1.0.tar.gz
        touch $out
      '';

  # `update` re-resolves through the network, so its check is the CI job of
  # the same name (tests/update.sh). What can run in the sandbox is that the
  # fixture it starts from is a locked project whose six is older than
  # pyproject.toml allows: pdm.lock pins six 1.15.0 and the lockfile passes
  # the stale check.
  conformance-update =
    let
      project = build { src = fixture "update"; };
    in
    runCommand "conformance-update" { } ''
      [ "${project.environment.name}" = "update-environment" ]
      grep -q 'version = "1.15.0"' ${./fixtures/update/pdm.lock}
      touch $out
    '';

  # The simple fixture kept external: its `src` holds the project and
  # pdm.lock, and the build reads pdm-purifier.lock.json from outside it.
  conformance-external =
    let
      external = build {
        src = fixtureWithout [ "pdm-purifier.lock.json" ] "simple";
        lockFile = builtins.path {
          path = ./fixtures/simple/pdm-purifier.lock.json;
          name = "pdm-purifier.lock.json";
        };
      };
    in
    runCommand "conformance-external" { } ''
      [ "$(${lib.getExe external.programs.simple} World)" = "Hello, World, from simple" ]
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

  # The project's tests, which the builder runs with its test group.
  simple-tests = simple.tests;

  # `pdm build` makes the sdist and the wheel that the lock run recorded,
  # which are the release, and the fetches list every locked file the
  # build fetched.
  simple-package =
    assert simple.release == simple.packages.simple;
    assert lib.any (entry: lib.hasPrefix "attrs-" (entry.file or "")) simple.fetches;
    assert lib.all (entry: entry ? hash) simple.fetches;
    runCommand "simple-package" { } ''
      test -f ${simple.packages.simple.sdist}
      test -f ${simple.packages.simple.wheel}
      ${pkgs.unzip}/bin/unzip -l ${simple.packages.simple.wheel} | grep -q 'simple/__init__.py'
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
