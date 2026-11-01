# SPDX-License-Identifier: MIT
#
# nixpkgs' PDM with the pdm-purifier plugin among its dependencies, so that
# PDM loads the plugin from its own installation. The plugin changes nothing
# until PDM_PURIFIER_MODE is set.
{
  pdm,
  plugin,
}:
pdm.overridePythonAttrs (old: {
  dependencies = (old.dependencies or [ ]) ++ [ plugin ];
  # PDM's own test suite already ran for the package this overrides.
  doCheck = false;
  doInstallCheck = false;
})
