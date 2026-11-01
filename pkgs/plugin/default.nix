# SPDX-License-Identifier: MIT
#
# The pdm-purifier plugin, built with `python3`, the interpreter nixpkgs'
# PDM runs on. PDM finds it through its `pdm` entry point.
{
  lib,
  python3,
}:
let
  python = python3;
in
python.pkgs.buildPythonPackage {
  pname = "pdm-purifier";
  version = lib.removeSuffix "\n" (builtins.readFile ../../version.txt);
  pyproject = true;

  src = lib.fileset.toSource {
    root = ../..;
    fileset = lib.fileset.unions [
      ../../version.txt
      ../../plugin
    ];
  };
  sourceRoot = "source/plugin";
  # setuptools reads the version only from inside the plugin directory.
  postPatch = ''
    cp ../version.txt version.txt
  '';

  build-system = [ python.pkgs.setuptools ];

  # The plugin imports PDM, which is the program that loads it, so PDM is
  # not one of its dependencies.
  dontCheckRuntimeDeps = true;
  doCheck = false;

  meta = {
    description = "The PDM plugin of pdm-purifier";
    license = lib.licenses.mit;
  };
}
