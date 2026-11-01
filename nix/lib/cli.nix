# SPDX-License-Identifier: MIT
#
# What the `pdm-purifier` command builds for a project, with the nixpkgs and
# the PDM the command was built with:
# - with `package`, that local distribution's sdist and wheel, which
#   `publish` uploads;
# - without it, the manifest that `pdm-purifier prefetch` keeps for the
#   plugin to serve PDM from, for the Python version `pythonVersion` that
#   the project's environment runs.
#
# `src` is the absolute path of the directory that holds the project and
# the local packages it depends on by path. `projectDir` is the directory
# of the project inside `src`. `lockFile` is the absolute path of
# pdm-purifier.lock.json, inside the project or outside it.
{
  nixpkgs,
  # The store path of the PDM, with the plugin, that the command runs.
  pdm,
  # The source of the shared purifier library.
  purifier,
  src,
  projectDir ? ".",
  lockFile,
  package ? null,
  pythonVersion ? null,
}:
let
  pkgs = import nixpkgs { };

  # A directory without what PDM, Python and git leave in it.
  source = builtins.path {
    path = /. + src;
    name = "source";
    filter =
      p: type:
      !builtins.elem (baseNameOf p) [
        ".git"
        ".venv"
        "__pypackages__"
        "__pycache__"
        "dist"
        ".pdm-build"
        ".pdm-python"
        ".pdm-purifier"
      ];
  };

  # The interpreter's version picks the wheels. A build that needs the
  # interpreter itself runs in Nix with the package set's Python.
  python =
    if pythonVersion == null then
      pkgs.python3
    else
      pkgs.python3
      // {
        inherit pythonVersion;
      };

  buildPdmProject = import ./build-pdm-project.nix {
    inherit (pkgs) lib;
    purifier = import (builtins.storePath purifier) { inherit (pkgs) lib; };
  };

  project = buildPdmProject {
    inherit pkgs projectDir;
    src = source;
    lockFile = /. + lockFile;
    pdm = builtins.storePath pdm;
    python = if package == null then python else pkgs.python3;
  };
in
if package == null then
  project.manifest
else
  project.packages.${package}
    or (throw "pdm-purifier: ${package} is not a local distribution of this project; they are ${toString (builtins.attrNames project.packages)}")
