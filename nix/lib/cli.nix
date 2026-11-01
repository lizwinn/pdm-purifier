# SPDX-License-Identifier: MIT
#
# What the `pdm-purifier` command builds for a project, with the nixpkgs and
# the PDM the command was built with:
# - with `package`, that local distribution's sdist and wheel, which
#   `publish` uploads;
# - without it, the manifest that `pdm-purifier pdm` serves PDM from, for
#   the Python version `pythonVersion` that the project's environment runs.
#
# `src` is the absolute path of the directory that holds the project and
# the local packages it depends on by path. `projectDir` is the directory
# of the project inside `src`.
{
  nixpkgs,
  # The store path of the PDM, with the plugin, that the command runs.
  pdm,
  # The source of the shared purifier library.
  purifier,
  src,
  projectDir ? ".",
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

  buildPdmProject = pkgs.callPackage ./build-pdm-project.nix {
    pdm-purifier.pdm-with-plugin = builtins.storePath pdm;
    purifier = import (builtins.storePath purifier) { inherit (pkgs) lib; };
  };

  project = buildPdmProject {
    src = source;
    inherit projectDir;
    python = if package == null then python else pkgs.python3;
  };
in
if package == null then
  project.manifest
else
  project.packages.${package}
    or (throw "pdm-purifier: ${package} is not a local distribution of this project; they are ${toString (builtins.attrNames project.packages)}")
