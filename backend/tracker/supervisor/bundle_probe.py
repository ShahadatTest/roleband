"""Headless verification of an assembled app, using only a new scratch directory."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def validate_paths(scratch: Path, resources: Path, pgdata: Path, data: Path, python: Path) -> None:
    if (pgdata.resolve() != (scratch / 'db').resolve()
            or data.resolve() != (scratch / 'home/.roleband').resolve()
            or python.resolve() != (resources / 'python').resolve()
            or scratch.resolve().is_relative_to(resources.resolve())):
        raise ValueError('The bundle probe requires its own scratch state and bundled Python')


def snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob('*') if path.is_file() and not path.is_symlink()}


def probe(scratch: Path) -> dict[str, object]:
    from tracker import __version__
    from tracker.platform.embedded_db import ensure_server, run_psql, stop_server
    from tracker.platform.paths import DATA_DIR, REPO_ROOT

    pgdata = Path(os.environ.get('ROLEBAND_PGDATA', ''))
    validate_paths(scratch, REPO_ROOT, pgdata, DATA_DIR, Path(sys.prefix))
    if os.environ.get('ROLEBAND_DATABASE_URL'):
        raise ValueError('The bundle probe cannot use an external database')
    scratch.mkdir(mode=0o700, parents=True)
    (scratch / 'home').mkdir(mode=0o700)
    app = REPO_ROOT.parent.parent
    before = snapshot(app)
    began = time.monotonic()
    imports = ('numpy', 'onnxruntime', 'sklearn.cluster', 'tokenizers', 'cryptography.fernet',
               'asyncpg', 'psycopg2', 'curl_cffi', 'selectolax.lexbor', 'pydantic_core', 'uvloop',
               'roleband_robots', 'roleband_plugin_sdk', 'tracker.api.app', 'tracker.mcp.server')
    for name in imports:
        importlib.import_module(name)
    for name in ('playwright', 'apple_fm_sdk'):
        if importlib.util.find_spec(name) is not None:
            raise ValueError(f'Unexpected optional runtime package: {name}')
    metadata = json.loads((REPO_ROOT / 'runtime.json').read_text())
    if __version__ != metadata['version']:
        raise ValueError('Engine and bundle release versions differ')
    server = None
    try:
        server = ensure_server(pgdata, database='roleband_bundle_probe', required_extensions=('vector', 'pg_trgm'))
        result = run_psql(server.dsn(), server.bin_dir,
            "CREATE EXTENSION vector; CREATE EXTENSION pg_trgm; SELECT '[1,2,3]'::vector <-> '[1,2,4]'::vector")
        if result.splitlines()[-1] != '1':
            raise ValueError('Bundled pgvector query returned an unexpected result')
        venv = scratch / 'plugin-venv'
        subprocess.run([sys.executable, '-I', '-m', 'venv', '--system-site-packages', str(venv)], check=True, capture_output=True)
        wheels = sorted((REPO_ROOT / 'plugin-wheels').glob('*.whl'))
        if len(wheels) != 2:
            raise ValueError('Expected SDK and robots wheels')
        subprocess.run([str(venv / 'bin/python'), '-I', '-m', 'pip', 'install', '--no-index', '--no-deps',
                        '--ignore-installed', *map(str, wheels)], check=True, capture_output=True)
        subprocess.run([str(venv / 'bin/python'), '-I', '-c',
            'import roleband_plugin_sdk, roleband_robots; from pathlib import Path; import sys; '
            'assert Path(roleband_plugin_sdk.__file__).is_relative_to(Path(sys.prefix))'],
            check=True, capture_output=True)
    finally:
        if server is not None or (pgdata / 'postmaster.pid').exists():
            stop_server(pgdata)
    if snapshot(app) != before:
        raise ValueError('The bundle probe changed files inside the app')
    return {'ok': True, 'version': __version__, 'python': sys.version.split()[0], 'prefix': sys.prefix,
            'imports': list(imports), 'extensions': ['vector', 'pg_trgm'], 'plugin_wheels': 'installed offline',
            'bundle_unchanged': True, 'elapsed_seconds': round(time.monotonic() - began, 3)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()

    def timed_out(signum: int, frame: object) -> None:
        raise TimeoutError('The headless engine probe was interrupted or exceeded 120 seconds')

    signal.signal(signal.SIGALRM, timed_out)
    signal.signal(signal.SIGTERM, timed_out)
    signal.alarm(120)
    try:
        print(json.dumps(probe(args.scratch.absolute())))
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    main()
