# SPDX-License-Identifier: MIT
#
# The `pdm-purifier` library namespace. It holds nothing: the builder needs
# a package set, so it is the package `buildPdmProject` that the default
# package overlay adds.
{ ... }:
{

  overlay = final: prev: {
    pdm-purifier = prev.pdm-purifier or { };
  };

}
