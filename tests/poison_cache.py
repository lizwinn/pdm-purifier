# SPDX-License-Identifier: MIT
"""Populate a native PDM wheel cache with a valid, modified provided wheel."""
import os
from pathlib import Path
import sys
import zipfile
from pdm.core import Core

project_path, tools = map(Path, sys.argv[1:])
sys.path.insert(0, str(tools))
import python_repository
project = Core().create_project(root_path=str(project_path))
candidate = project.get_locked_repository().all_candidates['simple'][0]
cache = project.make_wheel_cache()
directory = cache.get_path_for_link(candidate.link, project.environment.spec)
directory.mkdir(parents=True, exist_ok=True)
original = Path(candidate.link.file_path)
stage = Path(os.environ['PDM_CACHE_DIR']) / 'modified' / original.name
stage.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(original) as archive, zipfile.ZipFile(stage, 'w') as modified:
    for entry in archive.infolist():
        contents = archive.read(entry)
        if entry.filename == 'simple/__init__.py':
            contents = b'class Greeting:\n def __init__(self, name): pass\n def text(self): return "MUTABLE CACHE SUBSTITUTED"\n'
        modified.writestr(entry, contents)
poison = directory / original.name
python_repository.rewrite(stage, poison, python_repository.wheel(original)[1], {})
assert cache.get(candidate.link, 'simple', project.environment.spec) == poison
print('Native PDM cache contains a valid modified wheel', flush=True)
