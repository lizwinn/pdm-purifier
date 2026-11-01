# SPDX-License-Identifier: MIT
"""The `pdm-purifier` command.

    pdm-purifier lock                 write pdm-purifier.lock.json
    pdm-purifier pdm ARGS...          run PDM offline on the locked files
    pdm-purifier publish [--package NAME] [-- PDM-PUBLISH-ARGS...]
                                      upload what the Nix build made

Every verb works on the PDM project in the current directory. The command
runs the PDM of its package, which has the pdm-purifier plugin, and builds
with the Nix library and nixpkgs it was built with
(PDM_PURIFIER_NIX_LIB, PDM_PURIFIER_NIXPKGS, PDM_PURIFIER_PDM).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

LOCKFILE = "pdm-purifier.lock.json"
STATE_DIR = ".pdm-purifier"


class Error(Exception):
    pass


def log(message: str) -> None:
    print(f"pdm-purifier: {message}", file=sys.stderr)


def setting(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise Error(f"{name} is not set; run the pdm-purifier package, which sets it")
    return value


def pdm_executable() -> str:
    return str(Path(setting("PDM_PURIFIER_PDM")) / "bin" / "pdm")


def project_root() -> Path:
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        raise Error(f"{root} has no pyproject.toml; run pdm-purifier in the PDM project's directory")
    return root


def inputs_hash(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update((root / "pdm.lock").read_bytes())
    digest.update((root / "pyproject.toml").read_bytes())
    return digest.hexdigest()


def read_lockfile(root: Path) -> dict:
    path = root / LOCKFILE
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise Error(f"{LOCKFILE} is not valid JSON ({error}); restore it from version control or run `pdm-purifier lock`") from None
    if not isinstance(data, dict):
        raise Error(f"{LOCKFILE} is not a pdm-purifier lockfile; run `pdm-purifier lock`")
    return data


def lock_is_current(root: Path) -> bool:
    path = root / LOCKFILE
    if not path.exists() or not (root / "pdm.lock").exists():
        return False
    return read_lockfile(root).get("inputsHash") == inputs_hash(root)


def source_root(root: Path) -> tuple[Path, str]:
    """The directory Nix reads, which holds the project and every local
    package pdm.lock names by path, and the project's place inside it."""
    lock = tomllib.loads((root / "pdm.lock").read_text())
    paths = [root.resolve()]
    for package in lock.get("package", []):
        if "path" in package:
            paths.append((root / package["path"]).resolve())
    common = Path(os.path.commonpath([str(p) for p in paths]))
    return common, os.path.relpath(root.resolve(), common)


def nix_build(root: Path, out_link: Path, **args: str) -> Path:
    src, project_dir = source_root(root)
    command = [
        "nix-build",
        str(Path(setting("PDM_PURIFIER_NIX_LIB")) / "cli.nix"),
        "--argstr", "nixpkgs", setting("PDM_PURIFIER_NIXPKGS"),
        "--argstr", "pdm", setting("PDM_PURIFIER_PDM"),
        "--argstr", "purifier", setting("PDM_PURIFIER_LIBRARY"),
        "--argstr", "src", str(src),
        "--argstr", "projectDir", project_dir,
        "--out-link", str(out_link),
    ]
    for key, value in args.items():
        command += ["--argstr", key, value]
    out_link.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(command, stdout=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise Error("the Nix build failed")
    return Path(result.stdout.strip().splitlines()[-1])


def lock(root: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="pdm-purifier-lock-") as work:
        env = dict(os.environ)
        env.update(
            PDM_PURIFIER_MODE="record",
            PDM_PURIFIER_RECORD=str(Path(work) / "record.jsonl"),
            # An empty cache, so that every build downloads, and so records,
            # its build requirements.
            PDM_CACHE_DIR=str(Path(work) / "cache"),
            PDM_CHECK_UPDATE="false",
        )
        result = subprocess.run([pdm_executable(), "purifier", "lock"], cwd=root, env=env)
    if result.returncode != 0:
        raise Error("the lock run failed")


def project_python_version(root: Path) -> str | None:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PDM_PURIFIER_")}
    found = subprocess.run(
        [pdm_executable(), "info", "--python"],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    if found.returncode != 0 or not found.stdout.strip():
        return None
    version = subprocess.run(
        [found.stdout.strip(), "-c", "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True,
        text=True,
    )
    return version.stdout.strip() if version.returncode == 0 else None


def run_pdm(root: Path, args: list[str]) -> int:
    env = dict(os.environ)
    if not lock_is_current(root):
        log(f"{LOCKFILE} is missing or out of date; running PDM the usual way. Run `pdm-purifier lock` to lock it.")
        return subprocess.run([pdm_executable(), *args], env=env).returncode
    extra = {}
    version = project_python_version(root)
    if version is not None:
        extra["pythonVersion"] = version
    manifest = nix_build(root, root / STATE_DIR / "manifest", **extra)
    data = json.loads(manifest.read_text())
    git = [("protocol.file.allow", "always")] + [(f"url.{g['store']}.insteadOf", g["url"]) for g in data.get("git", [])]
    env.update(
        PDM_PURIFIER_MODE="serve",
        PDM_PURIFIER_MANIFEST=str(manifest),
        GIT_CONFIG_COUNT=str(len(git)),
    )
    for i, (key, value) in enumerate(git):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    return subprocess.run([pdm_executable(), *args], env=env).returncode


def publish(root: Path, packages: list[str], publish_args: list[str]) -> None:
    if not lock_is_current(root):
        raise Error(f"{LOCKFILE} is missing or out of date; run `pdm-purifier lock` first")
    outputs = read_lockfile(root).get("outputs", [])
    by_name = {o["name"]: o for o in outputs}
    names = packages or sorted(by_name)
    if not names:
        raise Error("this project builds no distribution to publish")
    for name in names:
        if name not in by_name:
            raise Error(f"{name} is not a local distribution of this project; they are {', '.join(sorted(by_name))}")
        dist = nix_build(root, root / STATE_DIR / f"dist-{name}", package=name)
        package_dir = (root / by_name[name]["path"]).resolve()
        log(f"publishing {name} from {dist}")
        env = {k: v for k, v in os.environ.items() if not k.startswith("PDM_PURIFIER_")}
        result = subprocess.run(
            [pdm_executable(), "publish", "--project", str(package_dir), "--no-build", "--dest", str(dist), *publish_args],
            env=env,
        )
        if result.returncode != 0:
            raise Error(f"pdm publish failed for {name}")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "pdm":
        try:
            return run_pdm(project_root(), argv[1:])
        except Error as error:
            log(str(error))
            return 1
    parser = argparse.ArgumentParser(prog="pdm-purifier", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    verbs = parser.add_subparsers(dest="verb", required=True)
    verbs.add_parser("lock", help="write pdm-purifier.lock.json")
    verbs.add_parser("pdm", help="run PDM offline on the locked files")
    publish_parser = verbs.add_parser("publish", help="upload what the Nix build made")
    publish_parser.add_argument("--package", action="append", default=[], help="a local distribution to publish (repeatable)")
    publish_parser.add_argument("publish_args", nargs=argparse.REMAINDER, help="arguments for `pdm publish`, after --")
    options = parser.parse_args(argv)
    try:
        root = project_root()
        if options.verb == "lock":
            lock(root)
        elif options.verb == "publish":
            extra = options.publish_args
            if extra and extra[0] == "--":
                extra = extra[1:]
            publish(root, options.package, extra)
    except Error as error:
        log(str(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
