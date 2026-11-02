#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Native PDM development and publishing with Nix-supplied Python dependencies."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parent.parent
system = subprocess.check_output(['nix', 'eval', '--impure', '--raw', '--expr',
                                  'builtins.currentSystem'], text=True).strip()
snapshot = json.loads(subprocess.check_output(['nix', 'flake', 'metadata', '--json',
    '--no-write-lock-file', 'path:' + str(root)], text=True))['path']
with tempfile.TemporaryDirectory(prefix='pdm-native-composition-') as temporary:
    temporary = Path(temporary)
    subprocess.run(['nix-store', '--add-root', str(temporary / 'source'), '--realise', snapshot], check=True)
    cli = Path(subprocess.check_output(['nix', 'build', str(root) + '#default', '--print-out-paths',
        '--out-link', str(temporary / 'cli')], text=True).strip()) / 'bin/pdm-purifier'
    pdm = cli.parent / 'pdm'
    expression = """let
      f = builtins.getFlake ("path:" + builtins.getEnv "PDM_COMPOSITION_FLAKE");
      p = f.inputs.nixpkgs.legacyPackages.${builtins.currentSystem};
      api = p.python3.withPackages (ps: [ (ps.toPythonModule p.pdm) ]);
    in p.runCommand "pdm-composition-native-tools" {} ''
      mkdir -p "$out/bin"
      ln -s ${p.uv}/bin/uv "$out/bin/uv"
      ln -s ${p.python3.interpreter} "$out/bin/python"
      ln -s ${api}/bin/python "$out/bin/native-python"
      ln -s ${f.inputs.purifier}/tools "$out/purifier-tools"
    '' """
    tools = Path(subprocess.check_output(['nix', 'build', '--impure', '--print-out-paths',
        '--out-link', str(temporary / 'tools'), '--expr', expression], text=True,
        env=dict(os.environ, PDM_COMPOSITION_FLAKE=snapshot)).strip())
    project = temporary / 'project'
    source = project / 'src/pdm_composed/__init__.py'
    source.parent.mkdir(parents=True)
    source.write_text('import simple\ndef main():\n    print(simple.Greeting("Nix").text())\n')
    definition = project / 'pyproject.toml'
    definition.write_text('''[project]
name = "pdm-composed"
version = "1.0"
requires-python = ">=3.12"
dependencies = ["simple>=99"]
[project.scripts]
pdm-composed = "pdm_composed:main"
[build-system]
requires = ["pdm-backend"]
build-backend = "pdm.backend"
''')
    original = definition.read_bytes()
    env = dict(os.environ, PDM_CHECK_UPDATE='false', PDM_VENV_BACKEND='venv')
    def run(*arguments, **kwargs):
        return subprocess.run([str(value) for value in arguments], cwd=project, env=env, check=True, **kwargs)
    reference = 'path:' + snapshot + '#checks.' + system + '.composition-producer'
    run(cli, 'lock', '--input', reference)
    lockfile, native = project / 'pdm-purifier.lock.json', project / 'pdm.lock'
    lock = json.loads(lockfile.read_text())
    assert len(lock['projectInputs']) == 1
    assert not lock['urls'], 'provided runtime files leaked into the download lock'
    before = lockfile.read_bytes(), native.read_bytes()
    run(cli, 'lock')
    assert before == (lockfile.read_bytes(), native.read_bytes()), 'relocking changed the pinned graph'
    run(cli, 'prefetch')
    output = subprocess.check_output([str(pdm), 'run', 'pdm-composed'], cwd=project, env=env, text=True)
    assert output.strip() == 'Hello, Nix, from simple', output
    assert definition.read_bytes() == original
    configuration = project / 'pdm.toml'
    saved = configuration.read_bytes() if configuration.exists() else None
    env['PDM_CACHE_DIR'] = str(temporary / 'poisoned-cache')
    try:
        run(pdm, 'config', '--local', 'install.cache', 'true')
        run(tools / 'bin/native-python', root / 'tests/poison_cache.py', project, tools / 'purifier-tools')
        run(pdm, 'sync', '--reinstall')
        output = subprocess.check_output([str(pdm), 'run', 'pdm-composed'], cwd=project, env=env, text=True)
        assert output.strip() == 'Hello, Nix, from simple', output
        run(project / '.venv/bin/python', '-c',
            'import simple; from pathlib import Path; assert Path(simple.__file__).resolve().is_relative_to(Path(".venv").resolve())')
    finally:
        env.pop('PDM_CACHE_DIR', None)
        if saved is None:
            configuration.unlink(missing_ok=True)
        else:
            configuration.write_bytes(saved)
    module = importlib.util.spec_from_file_location('pdm_cli', root / 'cli/pdm_purifier_cli.py')
    api = importlib.util.module_from_spec(module)
    module.loader.exec_module(api)
    old = lock['projectInputs'][0]['nativeRepository']
    missing = '/nix/store/' + '0' * 32 + '-unavailable-python-projection'
    assert not Path(missing).exists()
    native.write_text(native.read_text().replace(old, missing))
    lock = json.loads(lockfile.read_text())
    lock['projectInputs'][0]['nativeRepository'] = missing
    lock['inputsHash'] = api.inputs_hash(project, native)
    lock['contentHash'] = api.content_hash(lock)
    lockfile.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    bound = lockfile.read_bytes(), native.read_bytes()
    run(cli, 'prefetch')
    run(pdm, 'sync', '--reinstall')
    assert bound == (lockfile.read_bytes(), native.read_bytes()), 'development changed committed locks'
    expression = """let
      f = builtins.getFlake ("path:" + builtins.getEnv "PDM_COMPOSITION_FLAKE");
      p = import f.inputs.nixpkgs { overlays = [ f.overlays.default ]; };
      source = builtins.path {
        path = /. + builtins.getEnv "PDM_COMPOSITION_PROJECT";
        name = "source";
        filter = path: type: !(builtins.elem (baseNameOf path)
          [ ".git" ".venv" ".pdm-purifier" ".pdm-python" ".pdm-build" "__pycache__" "dist" "pdm.lock" ]);
      };
      project = p.pdm-purifier.buildPdmProject {
        src = source;
        pdmLock = /. + builtins.getEnv "PDM_COMPOSITION_NATIVE_LOCK";
        testCommand = "pdm run pdm-composed";
      };
    in [ project.tests project.packages.pdm-composed.projections.python ]"""
    built = json.loads(subprocess.check_output(['nix', 'build', '--impure', '--json',
        '--out-link', str(temporary / 'pure'), '--expr', expression], text=True,
        env=dict(env, PDM_COMPOSITION_FLAKE=snapshot, PDM_COMPOSITION_PROJECT=str(project),
                 PDM_COMPOSITION_NATIVE_LOCK=str(native))))
    repository = Path(next(value['outputs']['out'] for value in built
                          if value['outputs']['out'].endswith('-python-projection')))
    closure = subprocess.check_output(['nix-store', '--query', '--requisites', str(repository)], text=True)
    assert '-pdm-composed-publication-environment' in closure
    downstream = temporary / 'downstream'
    run(tools / 'bin/uv', 'venv', '--python', tools / 'bin/python', downstream)
    run(tools / 'bin/uv', 'pip', 'install', '--python', downstream / 'bin/python',
        '--no-index', '--find-links', repository, 'pdm-composed')
    output = subprocess.check_output([str(downstream / 'bin/pdm-composed')], text=True)
    assert output.strip() == 'Hello, Nix, from simple', output
    run(downstream / 'bin/python', '-c',
        'from importlib.metadata import version; assert "+nix." in version("pdm-composed"); assert "+nix." in version("simple")')
    uploads, portfile = temporary / 'uploads', temporary / 'port'
    server = subprocess.Popen([str(tools / 'bin/python'), str(root / 'tests/upload_server.py'),
                               '0', str(uploads), str(portfile)])
    try:
        deadline = time.monotonic() + 30
        while not portfile.exists():
            assert server.poll() is None and time.monotonic() < deadline, 'upload endpoint did not start'
            time.sleep(0.05)
        run(cli, 'publish', '--package', 'pdm-composed', '--', '--repository',
            'http://127.0.0.1:' + portfile.read_text() + '/', '--username', 'test', '--password', 'test')
        publication = (project / '.pdm-purifier/dist-pdm-composed').resolve()
        assert {path.name for path in uploads.iterdir()} == {path.name for path in publication.glob('*.whl')}
        for path in publication.glob('*.whl'):
            assert path.read_bytes() == (uploads / path.name).read_bytes()
    finally:
        server.terminate()
        server.wait(timeout=10)
    assert definition.read_bytes() == original
    print('PDM NATIVE, PURE, IMMUTABLE CACHE AND ORDINARY DOWNSTREAM COMPOSITION PASSED', flush=True)
