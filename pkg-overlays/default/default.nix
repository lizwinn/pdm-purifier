# SPDX-License-Identifier: MIT
#
# The default package overlay. It adds the packages of pkgs/ under
# `pkgs.pdm-purifier` (`.plugin`, `.pdm-with-plugin`, `.cli`). A consumer
# that lists this flake in `projects` holds it as `pdm-purifier/default`,
# which its package sets apply by default. The builder is in the library, as
# `lib.pdm-purifier.buildPdmProject`.
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
    };
}
