# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.pdm-purifier` (`.plugin`, `.pdm-with-plugin`, `.cli`), and the builder
# `pkgs.buildPdmProject` (nix/lib/build-pdm-project.nix). The builder is a
# package for `callPackage`, so `buildPdmProject.override` replaces the
# packages it takes. A consumer that lists this flake in `projects` holds
# the overlay as `pdm-purifier/default`, which its package sets apply by
# default.
#
# The command takes the source of the shared purifier library, for the
# builds it runs outside a flake.
{ closure-lib, closure-inputs, ... }:
let
  packages = closure-lib.caisson.nixpkgs.mkPackagesOverlay ../../pkgs "pdm-purifier";
in
{
  overlay =
    final: prev:
    let
      added = packages final prev;
    in
    added
    // {
      pdm-purifier = added.pdm-purifier // {
        cli = added.pdm-purifier.cli.override { purifierSource = closure-inputs.purifier; };
      };
      buildPdmProject = final.callPackage ../../nix/lib/build-pdm-project.nix {
        inherit (closure-lib) purifier;
      };
    };
}
