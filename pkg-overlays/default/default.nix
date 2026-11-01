# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.pdm-purifier` (`.plugin`, `.pdm-with-plugin`, `.cli`), and the builder
# `pkgs.buildPdmProject` (nix/lib/build-pdm-project.nix) beside them, where
# nixpkgs keeps its own builders, so a package written for callPackage takes
# it by name. A consumer that lists this flake in `projects` holds it as
# `pdm-purifier/default`, which its package sets apply by default.
{ closure-lib, ... }:
let
  packages = closure-lib.caisson.nixpkgs.mkPackagesOverlay ../../pkgs "pdm-purifier";
in
{
  overlay =
    final: prev:
    packages final prev
    // {
      buildPdmProject = final.callPackage ../../nix/lib/build-pdm-project.nix { };
    };
}
