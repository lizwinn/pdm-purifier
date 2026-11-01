# SPDX-License-Identifier: MIT
#
# Reads pdm-purifier.lock.json of a project, and refuses it when it does
# not belong to the project's current pdm.lock and pyproject.toml.
#
# `pdm-purifier lock` stores a SHA-256 over pdm.lock and pyproject.toml, in
# that order (inputs_hash in plugin/src/pdm_purifier/lock.py). This file
# computes the same hash from the project and compares the two.
{
  # The project directory, which holds pyproject.toml and both lockfiles.
  root,
  lockFile ? root + "/pdm-purifier.lock.json",
}:
let
  inherit (builtins) hashString pathExists readFile;

  version = import ./lock-version.nix;

  data =
    if pathExists lockFile then
      builtins.fromJSON (readFile lockFile)
    else
      throw "pdm-purifier: ${toString lockFile} is missing. Run `pdm-purifier lock` and commit it.";

  inputsHash = hashString "sha256" (
    readFile (root + "/pdm.lock") + readFile (root + "/pyproject.toml")
  );
in
if !(builtins.isAttrs data) then
  throw "pdm-purifier: pdm-purifier.lock.json is not a pdm-purifier lockfile. Run `pdm-purifier lock`."
else if (data.version or null) != version then
  throw "pdm-purifier: pdm-purifier.lock.json has format version ${
    toString (data.version or "none")
  }, and this library reads version ${toString version}. Run `pdm-purifier lock` with this pdm-purifier."
else if data.inputsHash != inputsHash then
  throw "pdm-purifier: pdm-purifier.lock.json does not match pdm.lock and pyproject.toml. Run `pdm-purifier lock`."
else
  data
