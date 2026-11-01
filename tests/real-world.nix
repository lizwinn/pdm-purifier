# SPDX-License-Identifier: MIT
#
# Builds a real project with the builder of this flake, for
# tests/real-world.sh:
#
#   nix build --impure -f tests/real-world.nix --argstr repo "$PWD" \
#     --argstr project "$project" environment
{ repo, project }:
let
  flake = builtins.getFlake "path:${repo}";
  pkgs = flake.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
in
flake.lib.pdm-purifier.buildPdmProject {
  inherit pkgs;
  src = /. + project;
}
