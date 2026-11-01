# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.pdm-purifier` (`.plugin`, `.pdm-with-plugin`, `.cli`), and the
# builder `pkgs.buildPdmProject` (nix/lib/build-pdm-project.nix) beside
# them, where nixpkgs keeps its own builders, so a package written for
# callPackage takes it by name. A consumer that lists this flake in
# `projects` holds it as `pdm-purifier/default`, which its package sets
# apply by default.
#
# Both take the shared purifier library: the builder its functions, and the
# command its source, for the builds it runs outside a flake.
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
