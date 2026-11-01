# SPDX-License-Identifier: MIT
"""`pdm purifier lock`: write pdm-purifier.lock.json beside pdm.lock.

pdm.lock pins every package with the names and SHA-256 hashes of its files,
but not their URLs, and it pins nothing that PDM installs to build a
package. This command fills in both:

1. It asks PDM's own finder, with platform filtering off, for the URL of
   every file in pdm.lock, so the lockfile covers every platform pdm.lock
   covers.
2. It runs every build that installing the project can need, with the
   recording transport under PDM: the project itself (sdist, wheel and
   editable wheel), each local and git dependency, and each registry or URL
   dependency that has an sdist and no wheel for every platform. PDM
   downloads each build's requirements through the transport, which writes
   them down.
3. It adds every file of each recorded build requirement's version, from
   the index page, so a build on another platform finds its wheels too.
4. It locks each git dependency, and each of its submodules, as a git
   checkout with its .git directory, which is what PDM clones from.

The command runs with PDM_PURIFIER_MODE=record, which `pdm-purifier lock`
sets together with an empty PDM cache.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    parse_sdist_filename,
    parse_wheel_filename,
)

from pdm_purifier.transport import RECORD_ENV, normalize_name

# The lock format this command writes. nix/lib/lock-version.nix holds the
# same number, and the Nix library refuses any other.
FORMAT_VERSION = 1
LOCKFILE = "pdm-purifier.lock.json"
VCS_KEYS = ("git", "hg", "svn", "bzr")


class LockError(Exception):
    pass


def sri(hex_digest: str) -> str:
    return "sha256-" + base64.b64encode(bytes.fromhex(hex_digest)).decode()


def inputs_hash(root: Path) -> str:
    """SHA-256 over pdm.lock and pyproject.toml, in that order. The Nix
    library computes the same hash to refuse a stale pdm-purifier.lock.json."""
    digest = hashlib.sha256()
    digest.update((root / "pdm.lock").read_bytes())
    digest.update((root / "pyproject.toml").read_bytes())
    return digest.hexdigest()


def name_and_version(filename: str) -> tuple[str, str] | None:
    try:
        name, version, _, _ = parse_wheel_filename(filename)
        return str(name), str(version)
    except InvalidWheelFilename:
        pass
    try:
        name, version = parse_sdist_filename(filename)
        return str(name), str(version)
    except InvalidSdistFilename:
        return None


def is_universal_wheel(filename: str) -> bool:
    if not filename.endswith(".whl"):
        return False
    _, _, _, tags = parse_wheel_filename(filename)
    return any(tag.abi == "none" and tag.platform == "any" for tag in tags)


def is_sdist(filename: str) -> bool:
    return not filename.endswith(".whl")


def wheel_scripts(wheel: Path) -> dict[str, list[str]]:
    """The console and GUI scripts a wheel installs, from its entry_points.txt."""
    import configparser

    scripts: dict[str, list[str]] = {"console": [], "gui": []}
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if n.endswith(".dist-info/entry_points.txt")]
        if not names:
            return scripts
        parser = configparser.ConfigParser(delimiters=("=",))
        parser.optionxform = str  # type: ignore[assignment,method-assign]
        parser.read_string(zf.read(names[0]).decode())
    for section, key in (("console_scripts", "console"), ("gui_scripts", "gui")):
        if parser.has_section(section):
            scripts[key] = sorted(parser.options(section))
    return scripts


class Locker:
    def __init__(self, project: Any) -> None:
        self.project = project
        self.environment = project.environment
        self.root = Path(project.root)
        self.work = Path(tempfile.mkdtemp(prefix="pdm-purifier-"))
        record = os.environ.get(RECORD_ENV)
        if not record or os.environ.get("PDM_PURIFIER_MODE") != "record":
            raise LockError("run `pdm-purifier lock`, which records the downloads of the builds")
        self.record = Path(record)
        # Entries by store path in the output tree, so every file appears once.
        self.artifacts: dict[str, dict] = {}
        self.git: dict[str, dict] = {}
        self._pages: dict[str, dict[str, Any]] = {}

    # -- index lookups -----------------------------------------------------

    def links(self, name: str) -> dict[str, Any]:
        """Every file of ``name`` on the project's indexes, for every
        platform, by file name. The first index that lists a file wins."""
        key = normalize_name(name)
        if key not in self._pages:
            found: dict[str, Any] = {}
            with self.environment.get_finder(env_spec=self.environment.allow_all_spec) as finder:
                for package in finder.find_all_packages(name, allow_yanked=True):
                    link = package.link
                    if link is None or link.is_vcs or link.is_file:
                        continue
                    found.setdefault(link.filename, link)
            self._pages[key] = found
        return self._pages[key]

    def add_artifact(self, name: str, filename: str, url: str, sha256: str, requires_python: str | None) -> None:
        parsed = name_and_version(filename)
        if parsed is None:
            raise LockError(f"{name}: {filename} is not a wheel or an sdist")
        entry = {
            "name": normalize_name(name),
            "version": parsed[1],
            "file": filename,
            "path": filename,
            "url": url,
            "mirrors": [],
            "hash": sri(sha256),
            "requiresPython": requires_python,
        }
        previous = self.artifacts.get(filename)
        if previous is not None and previous["hash"] != entry["hash"]:
            raise LockError(f"two different files are named {filename}")
        self.artifacts[filename] = entry

    def link_sha256(self, link: Any) -> str:
        hashes = link.hashes or {}
        if "sha256" in hashes:
            return hashes["sha256"]
        if link.hash_name == "sha256" and link.hash:
            return link.hash
        response = self.environment.session.get(link.url_without_fragment)
        response.raise_for_status()
        return hashlib.sha256(response.content).hexdigest()

    # -- pdm.lock ----------------------------------------------------------

    def packages(self) -> list[dict]:
        try:
            return list(self.project.lockfile["package"])
        except KeyError:
            return []

    def lock_registry_package(self, package: dict) -> None:
        name = package["name"]
        for item in package.get("files", []):
            algo, _, digest = item["hash"].partition(":")
            if algo != "sha256":
                raise LockError(f"{name}: pdm.lock has a {algo} hash; pdm-purifier needs sha256")
            if "url" in item:
                url = item["url"]
                filename = url.rsplit("/", 1)[-1].split("#")[0]
                requires_python = None
                link = self.links(name).get(filename)
                if link is not None:
                    requires_python = link.requires_python
            else:
                filename = item["file"]
                link = self.links(name).get(filename)
                if link is None:
                    raise LockError(f"{name}: none of the project's indexes lists {filename}")
                url = link.url_without_fragment
                requires_python = link.requires_python
            self.add_artifact(name, filename, url, digest, requires_python)

    def lock_url_package(self, package: dict) -> None:
        url = package["url"].split("#")[0]
        filename = url.rsplit("/", 1)[-1]
        for item in package.get("files", []):
            algo, _, digest = item["hash"].partition(":")
            if algo != "sha256":
                raise LockError(f"{package['name']}: pdm.lock has a {algo} hash; pdm-purifier needs sha256")
            self.add_artifact(package["name"], filename, url, digest, None)

    # -- git ---------------------------------------------------------------

    def git_command(self, *args: str, cwd: Path | None = None) -> str:
        result = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)
        return result.stdout

    def prefetch(self, url: str, rev: str) -> str:
        out = subprocess.run(
            ["nix-prefetch-git", "--quiet", "--leave-dotGit", "--url", url, "--rev", rev],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return json.loads(out)["hash"]

    def add_git(self, name: str, url: str, rev: str) -> None:
        if url in self.git:
            if self.git[url]["git"]["rev"] != rev:
                raise LockError(f"{url} is locked at two revisions; pdm-purifier keeps one per URL")
            return
        self.git[url] = {
            "name": name,
            "path": f"git/{normalize_name(name)}-{rev[:12]}",
            "git": {"url": url, "rev": rev, "submodules": False, "leaveDotGit": True},
            "hash": self.prefetch(url, rev),
        }

    def lock_git_package(self, package: dict) -> Path:
        """Lock a git dependency and its submodules, and return its checkout,
        for the build that records its build requirements."""
        url = package["git"].removeprefix("git+")
        rev = package["revision"]
        name = package["name"]
        checkout = self.work / "git" / f"{normalize_name(name)}-{rev[:12]}"
        if not checkout.exists():
            self.git_command("clone", "--quiet", url, str(checkout))
            self.git_command("reset", "--hard", "--quiet", rev, cwd=checkout)
            if (checkout / ".gitmodules").exists():
                self.git_command("submodule", "update", "--init", "--recursive", "--quiet", cwd=checkout)
        self.add_git(name, url, rev)
        if (checkout / ".gitmodules").exists():
            listing = self.git_command(
                "submodule",
                "foreach",
                "--recursive",
                "--quiet",
                'echo "$(git config remote.origin.url) $sha1 $name"',
                cwd=checkout,
            )
            for line in listing.splitlines():
                sub_url, sub_rev, sub_name = line.split(" ", 2)
                self.add_git(f"{name}-{sub_name}", sub_url, sub_rev)
        subdirectory = package.get("subdirectory")
        return checkout / subdirectory if subdirectory else checkout

    # -- builds ------------------------------------------------------------

    def build(self, source: Path, *, sdist: bool = False, editable: bool = False) -> dict:
        """Build ``source`` and return what it produced: its name, version,
        file names and scripts, the outputs Nix exposes for a local
        distribution."""
        from pdm.builders import EditableBuilder, SdistBuilder, WheelBuilder

        out = self.work / "dist" / hashlib.sha256(str(source).encode()).hexdigest()[:16]
        out.mkdir(parents=True, exist_ok=True)
        self.project.core.ui.echo(f"Building {source} to record its build requirements", err=True)
        sdist_name = Path(SdistBuilder(source, self.environment).build(str(out))).name if sdist else None
        wheel = Path(WheelBuilder(source, self.environment).build(str(out)))
        if editable:
            EditableBuilder(source, self.environment).build(str(self.work / "editable"))
        name, version, _, tags = parse_wheel_filename(wheel.name)
        return {
            "name": normalize_name(str(name)),
            "version": str(version),
            "sdist": sdist_name,
            "wheel": wheel.name,
            "pure": any(tag.abi == "none" and tag.platform == "any" for tag in tags),
            "scripts": wheel_scripts(wheel),
        }

    def unpack_sdist(self, name: str, url: str) -> Path:
        response = self.environment.session.get(url)
        response.raise_for_status()
        filename = url.rsplit("/", 1)[-1]
        archive = self.work / "sdists" / filename
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(response.content)
        dest = self.work / "unpacked" / filename
        dest.mkdir(parents=True, exist_ok=True)
        if filename.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(dest)
        else:
            with tarfile.open(archive) as tf:
                tf.extractall(dest, filter="data")
        tops = list(dest.iterdir())
        return tops[0] if len(tops) == 1 and tops[0].is_dir() else dest

    def needs_build(self, filenames: list[str]) -> bool:
        """A package may be built from its sdist on some platform when no
        wheel installs on every platform."""
        return any(is_sdist(f) for f in filenames) and not any(is_universal_wheel(f) for f in filenames)

    def recorded(self) -> list[dict]:
        if not self.record.exists():
            return []
        return [json.loads(line) for line in self.record.read_text().splitlines() if line.strip()]

    def add_build_requirements(self) -> None:
        """Lock every file of each version the builds downloaded."""
        known = {entry["url"] for entry in self.artifacts.values()}
        versions: set[tuple[str, str]] = set()
        for item in self.recorded():
            if item["url"] in known:
                continue
            filename = item["url"].rsplit("/", 1)[-1]
            parsed = name_and_version(filename)
            if parsed is None:
                raise LockError(f"a build downloaded {item['url']}, which is not a distribution file")
            versions.add(parsed)
            link = self.links(parsed[0]).get(filename)
            requires_python = link.requires_python if link is not None else None
            self.add_artifact(parsed[0], filename, item["url"], item["sha256"], requires_python)
        for name, version in sorted(versions):
            for filename, link in self.links(name).items():
                if name_and_version(filename) == (name, version) and filename not in self.artifacts:
                    self.add_artifact(name, filename, link.url_without_fragment, self.link_sha256(link), link.requires_python)

    # -- the whole lock ----------------------------------------------------

    def run(self) -> dict:
        project = self.project
        if not project.lockfile.exists():
            raise LockError("pdm.lock is missing; run `pdm lock` first")
        if not project.is_lockfile_hash_match():
            raise LockError("pdm.lock does not match pyproject.toml; run `pdm lock` first")

        builds: list[tuple[Path, dict]] = []
        sdist_builds: list[tuple[str, str]] = []
        for package in self.packages():
            if any(key in package for key in VCS_KEYS):
                if "git" not in package:
                    raise LockError(f"{package['name']}: only git is supported among version control systems")
                builds.append((self.lock_git_package(package), {}))
            elif "path" in package:
                path = (self.root / package["path"]).resolve()
                if path.is_dir():
                    builds.append((path, {"editable": bool(package.get("editable")), "local": True}))
            elif "url" in package:
                self.lock_url_package(package)
                filenames = [package["url"].split("#")[0].rsplit("/", 1)[-1]]
                if self.needs_build(filenames):
                    sdist_builds.append((package["name"], package["url"].split("#")[0]))
            else:
                self.lock_registry_package(package)
                filenames = [e["file"] for e in self.artifacts.values() if e["name"] == normalize_name(package["name"])]
                if self.needs_build(filenames):
                    sdist = next(e for e in self.artifacts.values() if e["name"] == normalize_name(package["name"]) and is_sdist(e["file"]))
                    sdist_builds.append((package["name"], sdist["url"]))

        # The local distributions, whose builds are the project's outputs:
        # the project itself, and each path dependency inside the project.
        outputs: list[dict] = []
        if project.is_distribution:
            output = self.build(self.root, sdist=True, editable=True)
            output["path"] = "."
            outputs.append(output)
        for source, options in builds:
            output = self.build(source, sdist=options.get("local", False), editable=options.get("editable", False))
            if options.get("local"):
                output["path"] = os.path.relpath(source, self.root)
                outputs.append(output)
        for name, url in sdist_builds:
            self.build(self.unpack_sdist(name, url))
        self.add_build_requirements()

        find_links = [s.url for s in project.sources if s.type == "find_links" and s.url]
        return {
            "version": FORMAT_VERSION,
            "inputsHash": inputs_hash(self.root),
            "findLinks": sorted(find_links),
            "outputs": sorted(outputs, key=lambda o: o["name"]),
            "artifacts": [self.artifacts[k] for k in sorted(self.artifacts)],
            "git": [self.git[k] for k in sorted(self.git)],
        }

    def close(self) -> None:
        shutil.rmtree(self.work, ignore_errors=True)


def lock(project: Any) -> Path:
    locker = Locker(project)
    try:
        data = locker.run()
    finally:
        locker.close()
    path = Path(project.root) / LOCKFILE
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    return path
