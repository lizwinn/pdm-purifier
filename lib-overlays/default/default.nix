# SPDX-License-Identifier: MIT
#
# The `pdm-purifier` library namespace, with the builder of the purifier
# contract:
#
#   lib.pdm-purifier.buildPdmProject { pkgs, src, fetchers ? { }, ... }
#
# (nix/lib/build-pdm-project.nix), and the reader of its lockfiles into the
# lock in memory:
#
#   lib.pdm-purifier.readLock { src, lockFile ? ..., projectDir ? "." }
#
# (nix/lib/read-lock.nix). Both build on the shared purifier library,
# which this library has as `lib.purifier`, because the flake lists
# `purifier` in its `projects`.
{ ... }:
{

  overlay = final: prev: {
    pdm-purifier = (prev.pdm-purifier or { }) // {
      buildPdmProject = import ../../nix/lib/build-pdm-project.nix {
        lib = final;
        inherit (final) purifier;
      };
      readLock = import ../../nix/lib/read-lock.nix { lib = final; };
    };
  };

}
