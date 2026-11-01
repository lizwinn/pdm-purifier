# SPDX-License-Identifier: MIT
#
# Whether a wheel installs with a given Python on a given Linux system, read
# from the compatibility tags in its file name (PEP 425 and PEP 600). The
# build uses this to choose which locked files to fetch for a system: the
# wheels that install, and the sdist of a package with no such wheel. uv
# makes the final choice among the fetched wheels when it installs.
{
  # The Python version, such as "3.14".
  pythonVersion,
  # The CPU name in a wheel's platform tag, such as "x86_64" or "aarch64".
  arch,
  # The glibc version of the system, such as "2.40".
  glibcVersion,
}:
let
  inherit (builtins)
    any
    elemAt
    filter
    fromJSON
    length
    match
    split
    substring
    stringLength
    ;

  splitOn =
    separator: text:
    filter builtins.isString (split (builtins.replaceStrings [ "." ] [ "\\." ] separator) text);

  versionParts = splitOn "." pythonVersion;
  major = elemAt versionParts 0;
  minor = fromJSON (elemAt versionParts 1);
  cpython = "cp${major}${toString minor}";

  glibcMinor = fromJSON (elemAt (splitOn "." glibcVersion) 1);

  # A python tag that names this major version, or an earlier minor
  # version of it ("py3", "py312").
  pythonTagMatches =
    tag:
    tag == "py${major}"
    || (
      let
        m = match "py${major}([0-9]+)" tag;
      in
      m != null && fromJSON (elemAt m 0) <= minor
    );

  # A stable-ABI tag combination: "cp3X" with "abi3", for X up to this
  # minor version.
  stableAbiMatches =
    tag:
    let
      m = match "cp${major}([0-9]+)" tag;
    in
    m != null && fromJSON (elemAt m 0) <= minor;

  platformMatches =
    tag:
    let
      legacy = {
        "manylinux1_${arch}" = 5;
        "manylinux2010_${arch}" = 12;
        "manylinux2014_${arch}" = 17;
      };
      # manylinux_2_N: glibc 2.N or later.
      perennial = match "manylinux_2_([0-9]+)_${arch}" tag;
    in
    tag == "any"
    || tag == "linux_${arch}"
    || (legacy ? ${tag} && legacy.${tag} <= glibcMinor)
    || (perennial != null && fromJSON (elemAt perennial 0) <= glibcMinor);

  tagsMatch =
    python: abi: platform:
    platformMatches platform
    && (
      (abi == "none" && (pythonTagMatches python || python == cpython))
      || (abi == "abi3" && stableAbiMatches python)
      || (abi == cpython && python == cpython)
    );
in
fileName:
let
  stem = substring 0 (stringLength fileName - 4) fileName;
  parts = splitOn "-" stem;
  count = length parts;
  tag = n: splitOn "." (elemAt parts (count - n));
in
count >= 5
&& any (python: any (abi: any (platform: tagsMatch python abi platform) (tag 1)) (tag 2)) (tag 3)
