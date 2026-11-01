# SPDX-License-Identifier: MIT
{ closure-lib, ... }:
{
  config,
  inputs,
  lib,
  ...
}:
{

  imports = [
    inputs.flake-parts.flakeModules.partitions
    closure-lib.caisson.modules.flake."purifier/purifier-packages"
  ];

  debug = false;

  # The scope `pkgs.pdm-purifier` is the `default` entry of this flake's
  # package overlay registry (pkg-overlays/): the package set applies it by
  # default, and the flake exports it as `pkgOverlays` and as the plain
  # `overlays.default`. The scope also holds the builder, which is a
  # function, so the module `purifier-packages` of the shared library
  # publishes the derivations of the scope as the `packages` output.
  purifier.scope = "pdm-purifier";

  caisson.libOverlays.exported = libOverlays: {
    inherit (libOverlays) default;
  };

  # `nix run github:nix-purifiers/pdm-purifier -- lock` writes
  # pdm-purifier.lock.json for the PDM project in the current directory.
  # `nix develop github:nix-purifiers/pdm-purifier` gives the PDM, with the
  # pdm-purifier plugin, that the Nix builds run, and the CLI.
  perSystem =
    { config, ... }:
    {
      packages.default = config.packages.cli;
      devShells.default = config.packages.cli.devShell;
    };

  partitionedAttrs.checks = "checks";
  partitionedAttrs.formatter = "formatter";

  partitions.formatter = {
    extraInputs = (lib.caisson.pins.flake-compat ../../../tests/dependencies).sources;
    module =
      { inputs, ... }:
      {
        imports = [ inputs.treefmt-nix.flakeModule ];
        perSystem.treefmt.programs.nixfmt.enable = true;
      };
  };

  partitions.checks = {
    extraInputs = (lib.caisson.pins.flake-compat ../../../tests/dependencies).sources;
    module =
      { inputs, self, ... }:
      {
        imports = [ inputs.treefmt-nix.flakeModule ];
        perSystem =
          { pkgs, system, ... }:
          {
            checks = import ../../../tests {
              inherit pkgs;
              overlay = self.overlays.default;
              inherit (self.lib.pdm-purifier) readLock;
              inherit (self.packages.${system}) cli;
            };
            treefmt.programs.nixfmt.enable = true;
          };
      };
  };

}
