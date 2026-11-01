# SPDX-License-Identifier: MIT
#
# Builds a PDM project in the Nix sandbox from pdm.lock and
# pdm-purifier.lock.json.
#
# For the system and Python it builds with, this function picks the locked
# files that installing the project can need: for each locked version, its
# wheels that install here, or else its sdist. It fetches each file and each
# locked git checkout, and writes a manifest of them. PDM then runs with the
# pdm-purifier plugin in serve mode: the plugin answers every request PDM
# makes from the manifest, so PDM installs from pdm.lock, and builds what it
# has to build, with no network and no other files.
#
# The result has:
# - `environment`: a virtual environment with the project and its runtime
#   dependencies installed (the locked groups in `groups`), and the
#   project's scripts in `bin/`.
# - `packages.<name>`, for the project and each local package it depends on
#   by path: what `pdm build` makes, its sdist and wheel, which is what
#   `pdm publish` uploads, with the attributes `sdist` and `wheel` naming the
#   two files.
# - `programs.<script>`: each console and GUI script of the project and its
#   local packages, from `environment`, for `nix run`.
# - `manifest`: the manifest that `pdm-purifier pdm` serves PDM from.
{
  lib,
  stdenv,
  runCommand,
  writeText,
  fetchgit,
  fetchhg,
  fetchsvn,
  fetchbzr,
  git,
  glibc,
  python3,
  pdm-purifier,
}:
{
  # The directory that holds everything the project reads: the project
  # itself and the local packages it depends on by path.
  src,
  # The project directory inside `src`, which holds pyproject.toml, pdm.lock
  # and pdm-purifier.lock.json.
  projectDir ? ".",
  # The Python the project builds and runs with. It must satisfy the
  # project's requires-python.
  python ? python3,
  # The pdm.lock groups that `environment` installs.
  groups ? [ "default" ],
  # A replacement for the fetcher of locked files; see nix/lib/fetch.nix.
  fetchurl ? null,
  # What the builds of sdists and local packages need beyond Python and a C
  # compiler: tools such as pkg-config, and the system libraries a C
  # extension links against.
  nativeBuildInputs ? [ ],
  buildInputs ? [ ],
}:
let
  inherit (builtins)
    attrNames
    concatMap
    convertHash
    filter
    groupBy
    listToAttrs
    map
    ;

  root = if projectDir == "." then src else src + "/${projectDir}";
  lock = import ./lock.nix { inherit root; };
  fetch = import ./fetch.nix { inherit fetchurl; };
  pyproject = builtins.fromTOML (builtins.readFile (root + "/pyproject.toml"));
  projectName = pyproject.project.name or "project";

  platform = stdenv.hostPlatform;
  target = "Python ${python.pythonVersion} on ${platform.system}";
  installs = import ./wheels.nix {
    inherit (python) pythonVersion;
    arch = platform.parsed.cpu.name;
    glibcVersion = glibc.version;
  };

  isWheel = entry: lib.hasSuffix ".whl" entry.file;

  # For each locked version, the files a build on this system may install:
  # its wheels that install, or else its sdist.
  versions = groupBy (entry: "${entry.name}==${entry.version}") lock.artifacts;
  chosen = concatMap (
    key:
    let
      entries = versions.${key};
      wheels = filter (entry: isWheel entry && installs entry.file) entries;
      sdists = filter (entry: !isWheel entry) entries;
    in
    if wheels != [ ] then
      wheels
    else if sdists != [ ] then
      sdists
    else
      throw "pdm-purifier: no wheel of ${key} installs with ${target}, and it has no sdist"
  ) (attrNames versions);

  storeName = file: lib.strings.sanitizeDerivationName file;

  fetched = map (
    entry:
    entry
    // {
      store = fetch {
        name = storeName entry.file;
        inherit (entry) url mirrors hash;
      };
      sha256 = convertHash {
        inherit (entry) hash;
        toHashFormat = "base16";
      };
    }
  ) chosen;

  # The plain checkout of a git entry, without .git, whose hash fetchgit
  # reproduces.
  plainGitCheckout =
    entry:
    fetchgit {
      inherit (entry.git) url rev;
      leaveDotGit = false;
      fetchSubmodules = entry.git.submodules;
      inherit (entry) hash;
    };

  # A git checkout with a .git directory that holds the locked commit, for
  # PDM to clone from. A hash over a .git directory that fetchgit leaves is
  # not reproducible, so the entry pins the plain checkout and carries the
  # raw commit object, and this derivation rebuilds the repository: it
  # writes the checkout's tree, with each submodule commit (gitlink) of the
  # entry, then the commit object, and marks the commit as the boundary of a
  # shallow clone, so git needs none of its parents. It fails unless the
  # commit's ID is the locked revision and its tree is the tree it wrote.
  gitRepository =
    entry:
    runCommand "${storeName entry.name}-git-${builtins.substring 0 12 entry.git.rev}"
      {
        nativeBuildInputs = [ git ];
        checkout = plainGitCheckout entry;
        inherit (entry.git) rev;
        commitObject = entry.git.commitObject.object;
        gitlinks = lib.concatMapStrings (
          link: "${link.rev} ${link.path}\n"
        ) entry.git.commitObject.gitlinks;
        passAsFile = [ "gitlinks" ];
      }
      ''
        cp -r "$checkout" "$out"
        chmod -R u+w "$out"
        cd "$out"
        export HOME="$TMPDIR"
        git init --quiet
        git config core.autocrlf false
        git add --all --force
        while read -r sha path; do
          [ -n "$sha" ] || continue
          rmdir "$path" 2>/dev/null || true
          git update-index --add --cacheinfo "160000,$sha,$path"
        done < "$gitlinksPath"
        tree=$(git write-tree)
        printf '%s' "$commitObject" | base64 -d > "$TMPDIR/commit"
        written=$(git hash-object -t commit -w --literally "$TMPDIR/commit")
        if [ "$written" != "$rev" ]; then
          echo "pdm-purifier: the commit object of ${entry.git.url} hashes to $written, not $rev" >&2
          exit 1
        fi
        if [ "$(git cat-file commit "$rev" | head -n 1)" != "tree $tree" ]; then
          echo "pdm-purifier: the checkout of ${entry.git.url} does not have the tree of $rev" >&2
          exit 1
        fi
        echo "$rev" > .git/shallow
        git update-ref refs/heads/main "$rev"
        git symbolic-ref HEAD refs/heads/main
        git read-tree "$rev"
        for d in $(cut -d' ' -f2- < "$gitlinksPath"); do mkdir -p "$d"; done
      '';

  # A version control checkout of the lock, fetched with the nixpkgs fetcher
  # of its kind, as the shared purifier library's entry kinds describe.
  fetchCheckout =
    entry:
    if entry ? git then
      if entry.git.leaveDotGit then gitRepository entry else plainGitCheckout entry
    else if entry ? hg then
      fetchhg {
        inherit (entry.hg) url rev;
        inherit (entry) hash;
      }
    else if entry ? svn then
      fetchsvn {
        inherit (entry.svn)
          url
          rev
          ignoreExternals
          ignoreKeywords
          ;
        inherit (entry) hash;
      }
    else if entry ? bzr then
      fetchbzr {
        inherit (entry.bzr) url rev;
        inherit (entry) hash;
      }
    else
      throw "pdm-purifier: pdm-purifier.lock.json has a checkout of an unknown kind: ${builtins.toJSON entry}";

  checkouts = map (entry: entry // { store = fetchCheckout entry; }) lock.checkouts;
  gitCheckouts = filter (entry: entry ? git) checkouts;
  otherCheckouts = filter (entry: !(entry ? git)) checkouts;
  vcsOf =
    entry:
    lib.findFirst (kind: entry ? ${kind}) (throw "unreachable") [
      "hg"
      "svn"
      "bzr"
    ];

  manifest = writeText "pdm-purifier-manifest.json" (
    builtins.toJSON {
      files = listToAttrs (
        map (entry: {
          name = entry.url;
          value = "${entry.store}";
        }) fetched
      );
      projects = lib.mapAttrs (
        _: entries:
        map (entry: {
          inherit (entry) file url sha256;
          requiresPython = entry.requiresPython or null;
        }) entries
      ) (groupBy (entry: entry.name) fetched);
      findLinks = lock.findLinks or [ ];
      # Each locked git repository URL, to its checkout in the store.
      git = map (entry: {
        inherit (entry.git) url;
        store = "${entry.store}";
      }) gitCheckouts;
      # Each locked Mercurial, Subversion and Bazaar checkout, which the
      # plugin copies in place of a clone.
      vcs = map (
        entry:
        let
          kind = vcsOf entry;
        in
        {
          vcs = kind;
          inherit (entry.${kind}) url rev;
          inherit (entry) name version;
          subdirectory = entry.subdirectory or null;
          store = "${entry.store}";
        }
      ) otherCheckouts;
    }
  );

  # Git reads its configuration from GIT_CONFIG_COUNT, GIT_CONFIG_KEY_<n>
  # and GIT_CONFIG_VALUE_<n>. Each locked repository URL is rewritten to its
  # checkout in the store, which has the locked commit in its .git.
  gitConfig = [
    {
      key = "protocol.file.allow";
      value = "always";
    }
    {
      key = "safe.directory";
      value = "*";
    }
  ]
  ++ map (entry: {
    key = "url.${entry.store}.insteadOf";
    value = entry.git.url;
  }) gitCheckouts;

  gitEnvironment = lib.concatStrings (
    lib.imap0 (i: item: ''
      export GIT_CONFIG_KEY_${toString i}=${lib.escapeShellArg item.key}
      export GIT_CONFIG_VALUE_${toString i}=${lib.escapeShellArg item.value}
    '') gitConfig
  );

  # The environment every PDM run in the sandbox gets.
  setupPdm = ''
    export HOME="$TMPDIR/home"
    mkdir -p "$HOME"
    export PDM_CACHE_DIR="$TMPDIR/pdm-cache"
    export PDM_CHECK_UPDATE=false
    export PDM_VENV_BACKEND=venv
    export PDM_PURIFIER_MODE=serve
    export PDM_PURIFIER_MANIFEST=${manifest}
    export GIT_CONFIG_COUNT=${toString (lib.length gitConfig)}
    ${gitEnvironment}
  '';

  buildTools = [
    pdm-purifier.pdm-with-plugin
    git
    python
  ]
  ++ nativeBuildInputs;

  # The project's outputs, recorded by `pdm-purifier lock`.
  outputs = lock.outputs or [ ];
  isProjectOutput = output: output.path == ".";
  projectIsDistribution = lib.any isProjectOutput outputs;

  environment = stdenv.mkDerivation {
    name = "${projectName}-environment";
    inherit src buildInputs;
    nativeBuildInputs = buildTools;
    dontConfigure = true;
    dontFixup = true;
    buildPhase = ''
      runHook preBuild
      ${setupPdm}
      cd ${lib.escapeShellArg projectDir}
      ${python.interpreter} -m venv --without-pip "$out"
      # PDM installs into the virtual environment of the interpreter the
      # project uses.
      pdm use --first --ignore-remembered "$out/bin/python"
      pdm sync --prod --no-editable ${
        lib.concatMapStringsSep " " (group: "-G ${lib.escapeShellArg group}") groups
      } ${lib.optionalString (!projectIsDistribution) "--no-self"}
      runHook postBuild
    '';
    dontInstall = true;
    passthru = { inherit manifest; };
  };

  package =
    output:
    let
      dist = stdenv.mkDerivation {
        name = "${output.name}-${output.version}-dist";
        inherit src buildInputs;
        nativeBuildInputs = buildTools;
        dontConfigure = true;
        dontFixup = true;
        buildPhase = ''
          runHook preBuild
          ${setupPdm}
          cd ${lib.escapeShellArg projectDir}
          pdm use --first --ignore-remembered --project ${lib.escapeShellArg output.path} ${python.interpreter}
          pdm build --no-clean --dest "$out" --project ${lib.escapeShellArg output.path}
          runHook postBuild
        '';
        dontInstall = true;
      };
      # A wheel with platform tags is named for the system it was built on,
      # so its file is copied out under a name of its own.
      wheel =
        if output.pure then
          "${dist}/${output.wheel}"
        else
          runCommand "${output.name}-${output.version}-wheel" { } ''
            cp ${dist}/*.whl "$out"
          '';
    in
    dist
    // {
      inherit wheel;
      sdist = if output.sdist != null then "${dist}/${output.sdist}" else null;
    };

  programs = listToAttrs (
    concatMap (
      output:
      map (script: {
        name = script;
        value = runCommand script { meta.mainProgram = script; } ''
          mkdir -p "$out/bin"
          ln -s ${environment}/bin/${script} "$out/bin/${script}"
        '';
      }) (output.scripts.console ++ output.scripts.gui)
    ) outputs
  );
in
{
  inherit environment manifest programs;
  packages = listToAttrs (
    map (output: {
      inherit (output) name;
      value = package output;
    }) outputs
  );
}
