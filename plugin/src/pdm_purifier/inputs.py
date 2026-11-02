# SPDX-License-Identifier: MIT
"""Install Nix-authoritative native PDM bindings without editing the project."""
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
import zipfile

from pdm.utils import comparable_version, normalize_name

from pdm_purifier import transport

INPUTS_ENV = 'PDM_PURIFIER_PROJECT_INPUTS'
_bound_wheels: dict[str, Path] = {}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _configuration(project: Any) -> dict | None:
    filename = os.environ.get(INPUTS_ENV)
    if filename:
        return json.loads(Path(filename).read_text())
    mode = os.environ.get(transport.MODE_ENV)
    if mode in ('off', 'record'):
        return None
    if not mode:
        lockfile = Path(os.environ.get(transport.LOCKFILE_ENV) or Path(project.root) / 'pdm-purifier.lock.json')
        if not lockfile.exists() or not json.loads(lockfile.read_text()).get('projectInputs'):
            return None
        transport.activate(Path(project.root))
    filename = transport._manifest().get('pythonInputs')
    return json.loads(Path(filename).read_text()) if filename else None


def _supplied(source: str, roots: list[str]) -> bool:
    parsed = urlsplit(source)
    path = unquote(parsed.path) if parsed.scheme == 'file' else source
    return any(Path(path).is_relative_to(root) for root in roots)


def apply(project: Any, options: Any = None, **kwargs: Any) -> None:
    configuration = _configuration(project)
    _bound_wheels.clear()
    if not configuration:
        return
    _bound_wheels.update((str(Path(module['wheel']).resolve()), Path(module['wheel']))
                         for module in configuration['modules'].values())
    if options is not None:
        previous = getattr(options, 'override', None) or []
        if isinstance(previous, str):
            previous = [previous]
        options.override = [*previous, configuration['overrides']]
    if not project.lockfile.exists():
        return
    modules = configuration['modules']
    data = project.lockfile.open_for_read()
    changed = False
    for package in data.get('package', []):
        name = normalize_name(package['name'])
        source = package.get('path') or package.get('url')
        if name not in modules or not source or not _supplied(source, configuration['oldRepositories']):
            continue
        module = modules[name]
        wheel = Path(module['wheel'])
        parsed = urlsplit(source)
        original = Path(unquote(parsed.path) if parsed.scheme == 'file' else source)
        if original.resolve() == wheel.resolve() and package.get('version') == str(comparable_version(module['version'])):
            continue
        changed = True
        package['version'] = str(comparable_version(module['version']))
        package['path'] = str(wheel)
        package.pop('url', None)
        package['files'] = [{'file': wheel.name, 'hash': 'sha256:' + file_hash(wheel)}]
        with zipfile.ZipFile(wheel) as archive:
            metadata, = [name for name in archive.namelist() if name.endswith('.dist-info/METADATA')]
            model = BytesParser().parsebytes(archive.read(metadata))
        package['dependencies'] = model.get_all('Requires-Dist', [])
    if changed:
        project.lockfile.set_data(data)


def patch_immutable_inputs() -> None:
    """Use supplied wheel bytes even when writable native caches are present."""
    from importlib.metadata import Distribution
    from pdm.models.candidates import PreparedCandidate
    from pdm.installers.manager import InstallManager
    from pdm.installers.installers import install_wheel

    original_cache = PreparedCandidate._get_build_cache
    original_install = InstallManager.install
    if getattr(original_cache, '_pdm_purifier_inputs', False):
        return

    def supplied(link: Any) -> Path | None:
        if link is None or not link.is_file:
            return None
        return _bound_wheels.get(str(Path(link.file_path).resolve()))

    def cache(self: Any) -> Path | None:
        if supplied(self.link or self.candidate.link) is not None:
            return None
        return original_cache(self)

    def install(self: Any, candidate: Any) -> Any:
        prepared = candidate.prepare(self.environment)
        expected = supplied(prepared.link or candidate.link)
        if expected is None:
            return original_install(self, candidate)
        wheel = prepared.build()
        if wheel.resolve() != expected.resolve() and file_hash(wheel) != file_hash(expected):
            raise RuntimeError(f'pdm-purifier: native cache substituted the Nix wheel {expected.name}')
        # Native install caching can link to mutable unpacked packages. Copy
        # this exact immutable wheel through PDM's ordinary installer instead.
        destination = install_wheel(wheel, self.environment, direct_url=prepared.direct_url(),
            install_links=False, rename_pth=self.rename_pth, requested=candidate.requested)
        return Distribution.at(destination)

    cache._pdm_purifier_inputs = True
    PreparedCandidate._get_build_cache = cache
    InstallManager.install = install
