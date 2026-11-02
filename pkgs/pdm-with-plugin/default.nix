# SPDX-License-Identifier: MIT
#
# nixpkgs' PDM with the pdm-purifier plugin among its dependencies, so that
# PDM loads the plugin from its own installation. The plugin changes nothing
# until PDM_PURIFIER_MODE is set.
{
  pdm,
  plugin,
  lib,
  makeWrapper,
}:
let
  unlockedNotice = ''
    case "''${1:-}" in
      "" | --version | -V | --help | -h)
        if [ "''${PDM_PURIFIER:-1}" != 0 ] && [ -z "''${PDM_PURIFIER_MODE:-}" ]; then
          root="$PWD"
          while [ ! -f "$root/pyproject.toml" ] && [ "$root" != / ]; do
            root=$(dirname "$root")
          done
          lock="''${PDM_PURIFIER_LOCKFILE:-$root/pdm-purifier.lock.json}"
          if [ ! -e "$lock" ]; then
            echo "pdm-purifier: warning: no purifier lockfile found; running pdm impurely." >&2
            export PDM_PURIFIER_WARNING_SENT=1
          fi
        fi
        ;;
    esac
  '';
in
pdm.overridePythonAttrs (old: {
  dependencies = (old.dependencies or [ ]) ++ [ plugin ];
  nativeBuildInputs = (old.nativeBuildInputs or [ ]) ++ [ makeWrapper ];
  postFixup = (old.postFixup or "") + ''
    wrapProgram "$out/bin/pdm" --run ${lib.escapeShellArg unlockedNotice}
  '';
  # PDM's own test suite already ran for the package this overrides.
  doCheck = false;
  doInstallCheck = false;
})
