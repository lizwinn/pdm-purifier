# SPDX-License-Identifier: MIT
"""The HTTP transports that pdm-purifier puts under every PDM session.

PDM makes all of its HTTP requests through one httpx client per
environment, built by ``BaseEnvironment._build_session``. The plugin
replaces that client's transport, so the choice of transport covers index
pages, distribution files, URL dependencies and the build requirements of
isolated builds alike, whatever indexes the project names.

``PDM_PURIFIER_MODE`` selects the transport:

- ``record``: requests go to the network as usual, and every distribution
  file PDM downloads is appended to the JSON-lines file named by
  ``PDM_PURIFIER_RECORD``, with its URL and SHA-256.
- ``serve``: nothing reaches the network. Distribution files come from the
  Nix store, and an index page lists only the locked files of its project.
  The manifest named by ``PDM_PURIFIER_MANIFEST`` holds both.

- ``off``: the plugin changes nothing.

Without ``PDM_PURIFIER_MODE``, the plugin serves a project that
``pdm-purifier prefetch`` prepared, and changes nothing for any other
(``activate``).
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import httpx

MODE_ENV = "PDM_PURIFIER_MODE"
RECORD_ENV = "PDM_PURIFIER_RECORD"
MANIFEST_ENV = "PDM_PURIFIER_MANIFEST"
LOCKFILE_ENV = "PDM_PURIFIER_LOCKFILE"

DISTRIBUTION_SUFFIXES = (
    ".whl",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tar.xz",
    ".tar",
    ".zip",
)

SIMPLE_JSON = "application/vnd.pypi.simple.v1+json"


def normalize_name(name: str) -> str:
    """The PEP 503 normalized form of a project name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def without_fragment(url: httpx.URL) -> str:
    return str(url.copy_with(fragment=None))


def is_distribution(url: httpx.URL) -> bool:
    return url.path.lower().endswith(DISTRIBUTION_SUFFIXES)


class RecordingTransport(httpx.BaseTransport):
    """Passes each request on, and records the distribution files."""

    _lock = threading.Lock()

    def __init__(self, route: Callable[[httpx.URL], httpx.BaseTransport], record: Path) -> None:
        self._route = route
        self._record = record

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._route(request.url).handle_request(request)
        if request.method != "GET" or response.status_code != 200 or not is_distribution(request.url):
            return response
        # The decoded body is the file. It goes on to PDM without the
        # encoding headers, so PDM reads the bytes that were hashed.
        body = response.read()
        response.close()
        entry = {
            "url": without_fragment(request.url),
            "sha256": hashlib.sha256(body).hexdigest(),
        }
        with self._lock, self._record.open("a") as out:
            out.write(json.dumps(entry, sort_keys=True) + "\n")
        headers = [(k, v) for k, v in response.headers.items() if k.lower() not in ("content-encoding", "content-length")]
        return httpx.Response(
            response.status_code,
            headers=headers,
            content=body,
            request=request,
            extensions=response.extensions,
        )


class ServingTransport(httpx.BaseTransport):
    """Answers every request from the manifest, and nothing else."""

    def __init__(self, manifest: dict) -> None:
        # The URL of each locked file this build may install, to its store path.
        self._files: dict[str, str] = manifest["files"]
        # Each locked project, to the entries of its index page.
        self._projects: dict[str, list[dict]] = manifest["projects"]
        # The find-links locations of the project, each listing every file.
        self._find_links: set[str] = {u.rstrip("/") for u in manifest.get("findLinks", [])}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = without_fragment(request.url)
        if url in self._files:
            return httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                content=Path(self._files[url]).read_bytes(),
                request=request,
            )
        if url.rstrip("/") in self._find_links:
            return self._links_page(request, [e for entries in self._projects.values() for e in entries])
        segments = [s for s in request.url.path.split("/") if s]
        if segments:
            entries = self._projects.get(normalize_name(segments[-1]))
            if entries is not None:
                return self._index_page(request, segments[-1], entries)
        print(
            f"pdm-purifier: {url} is not in pdm-purifier.lock.json, and PDM is serving only the locked files. "
            "To change dependencies, run the command with PDM_PURIFIER_MODE=off (such as "
            "`PDM_PURIFIER_MODE=off pdm add <package>`), then run `pdm-purifier lock` and `pdm-purifier prefetch`.",
            file=sys.stderr,
        )
        return httpx.Response(404, request=request)

    def _index_page(self, request: httpx.Request, name: str, entries: list[dict]) -> httpx.Response:
        files = []
        for entry in entries:
            item = {
                "filename": entry["file"],
                "url": entry["url"],
                "hashes": {"sha256": entry["sha256"]},
            }
            if entry.get("requiresPython"):
                item["requires-python"] = entry["requiresPython"]
            files.append(item)
        page = {"meta": {"api-version": "1.0"}, "name": normalize_name(name), "files": files}
        return httpx.Response(
            200,
            headers={"content-type": SIMPLE_JSON},
            content=json.dumps(page).encode(),
            request=request,
        )

    def _links_page(self, request: httpx.Request, entries: list[dict]) -> httpx.Response:
        anchors = []
        for entry in entries:
            attr = ""
            if entry.get("requiresPython"):
                attr = f' data-requires-python="{html.escape(entry["requiresPython"])}"'
            href = html.escape(f"{entry['url']}#sha256={entry['sha256']}")
            anchors.append(f'<a href="{href}"{attr}>{html.escape(entry["file"])}</a>')
        body = "<!DOCTYPE html><html><body>\n" + "\n".join(anchors) + "\n</body></html>\n"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=body.encode(),
            request=request,
        )


PREFETCHED = ".pdm-purifier/manifest"
PREFETCHED_INPUTS = ".pdm-purifier/inputs"


def inputs_hash(root: Path) -> str:
    """SHA-256 over pdm.lock and pyproject.toml, in that order: the
    inputsHash that `pdm-purifier lock` records."""
    digest = hashlib.sha256()
    digest.update((root / "pdm.lock").read_bytes())
    digest.update((root / "pyproject.toml").read_bytes())
    return digest.hexdigest()


def activate(root: Path) -> None:
    """Choose serve mode for a project that `pdm-purifier prefetch` prepared.

    `pdm-purifier prefetch` keeps the manifest in .pdm-purifier/manifest,
    and the inputsHash it was made for in .pdm-purifier/inputs, beside the
    pdm-purifier lockfile: next to pdm.lock, or for an external build next
    to the lockfile that PDM_PURIFIER_LOCKFILE names. When
    PDM_PURIFIER_MODE is not set, and the project's pdm.lock and
    pyproject.toml still have that hash, PDM serves every download from the
    locked files. PDM_PURIFIER_MODE=off turns that off, for a command that
    changes the dependencies. A project changed since the prefetch runs PDM
    the usual way, with a warning.
    """
    if os.environ.get(MODE_ENV):
        return
    lockfile = os.environ.get(LOCKFILE_ENV)
    base = Path(lockfile).parent if lockfile else root
    manifest = base / PREFETCHED
    inputs = base / PREFETCHED_INPUTS
    if not manifest.exists() or not inputs.exists():
        return
    if not (root / "pdm.lock").exists() or inputs.read_text().strip() != inputs_hash(root):
        print(
            "pdm-purifier: pdm.lock or pyproject.toml changed since `pdm-purifier prefetch`, so PDM runs online. "
            "Run `pdm-purifier lock` and `pdm-purifier prefetch`.",
            file=sys.stderr,
        )
        return
    os.environ[MODE_ENV] = "serve"
    os.environ[MANIFEST_ENV] = str(manifest.resolve())
    # Git sends a clone of each locked repository to its checkout in the
    # store, which has the locked commit.
    rewrites = [("protocol.file.allow", "always")] + [
        (f"url.{g['store']}.insteadOf", g["url"]) for g in _manifest().get("git", [])
    ]
    start = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
    for i, (key, value) in enumerate(rewrites, start):
        os.environ[f"GIT_CONFIG_KEY_{i}"] = key
        os.environ[f"GIT_CONFIG_VALUE_{i}"] = value
    os.environ["GIT_CONFIG_COUNT"] = str(start + len(rewrites))


_manifest_cache: dict | None = None


def _manifest() -> dict:
    global _manifest_cache
    if _manifest_cache is None:
        path = os.environ.get(MANIFEST_ENV)
        if not path:
            raise RuntimeError(f"pdm-purifier: {MODE_ENV}=serve needs {MANIFEST_ENV}")
        _manifest_cache = json.loads(Path(path).read_text())
    return _manifest_cache


def install(session: httpx.Client) -> None:
    """Put the transport that PDM_PURIFIER_MODE selects under ``session``."""
    mode = os.environ.get(MODE_ENV)
    if not mode:
        return
    if mode == "off":
        return
    if mode == "record":
        record = os.environ.get(RECORD_ENV)
        if not record:
            raise RuntimeError(f"pdm-purifier: {MODE_ENV}=record needs {RECORD_ENV}")
        transport: httpx.BaseTransport = RecordingTransport(session._transport_for_url, Path(record))
    elif mode == "serve":
        transport = ServingTransport(_manifest())
    else:
        raise RuntimeError(f"pdm-purifier: unknown {MODE_ENV} {mode!r}")
    # httpx picks a transport per request with _transport_for_url, so one
    # instance attribute replaces both the default transport and the mounts.
    session._transport_for_url = lambda url: transport  # type: ignore[method-assign]
