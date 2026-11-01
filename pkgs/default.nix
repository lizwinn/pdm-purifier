# SPDX-License-Identifier: MIT
{ callPackage, ... }:
let
  plugin = callPackage ./plugin { };
  pdm-with-plugin = callPackage ./pdm-with-plugin { inherit plugin; };
in
{
  # The PDM plugin: the transports that record or serve PDM's downloads, and
  # `pdm purifier lock`.
  inherit plugin;
  # nixpkgs' PDM with the plugin installed. buildPdmProject and the CLI run
  # it.
  inherit pdm-with-plugin;
  # The `pdm-purifier` command: `lock`, `pdm` (PDM offline on the locked
  # files) and `publish`.
  cli = callPackage ./cli { inherit pdm-with-plugin; };
}
