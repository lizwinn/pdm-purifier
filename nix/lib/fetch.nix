# SPDX-License-Identifier: MIT
#
# The fetcher for locked files.
#
# By default each file is a fixed-output derivation on Nix's built-in
# fetcher (the same derivation <nix/fetchurl.nix> makes). A fixed-output
# store path depends only on its name and hash, so the default fetcher and
# nixpkgs' fetchurl produce the same paths.
#
# `fetchurl`, when given, replaces the built-in fetcher. It is called with
# { name, urls, hash } and is the place for credentials (nixpkgs' fetchurl
# takes `netrcPhase`) or further mirrors.
{
  fetchurl ? null,
}:
# A file entry of the shared purifier library: `url`, the `mirrors` that
# serve the same bytes, and the SRI `hash` of the file. Nix's built-in
# fetcher downloads from `url` alone; the mirrors are tried by a `fetchurl`
# passed in. The entries pdm-purifier writes have no mirrors, because an
# index such as PyPI keeps a file at its URL.
{
  name,
  url,
  mirrors ? [ ],
  hash,
}:
let
  urls = [ url ] ++ mirrors;
in
if fetchurl != null then
  fetchurl { inherit name urls hash; }
else
  derivation {
    inherit name url urls;
    builder = "builtin:fetchurl";
    system = "builtin";
    outputHash = hash;
    outputHashAlgo = "sha256";
    outputHashMode = "flat";
    unpack = false;
    executable = false;
    preferLocalBuild = true;
    impureEnvVars = [
      "http_proxy"
      "https_proxy"
      "ftp_proxy"
      "all_proxy"
      "no_proxy"
    ];
  }
