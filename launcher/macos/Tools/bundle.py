"""Assemble the standalone engine inside the native app as an ad-hoc signed release candidate.

Release signing happens later, on the candidate, with `signing.py seal`.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

from repo_paths import ROOT

from tracker.platform.releases import release_version

MACHO = {bytes.fromhex(value) for value in ('cffaedfe', 'cefaedfe', 'feedfacf', 'feedface', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca')}
MINIMUM_MACOS = (14, 0)
GROWTH_NOTE_LIMIT = 280
RUNTIME_LOCK = Path('launcher/macos/runtime-lock.txt')
DASHBOARD_STAMP = Path('dashboard/dist/.roleband-tree')
DASHBOARD_DIRTY = Path('dashboard/dist/.roleband-dirty')
# Everything the bundle takes from the repository besides the launcher and the built dashboard.
HEAD_PATHS = ('backend', 'sdk/python', 'robots/python', 'dashboard/package.json', 'dashboard/csp-policy.json',
              'CHANGELOG.md', 'LICENSE')
REQUIREMENT = re.compile(r'([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^\]]*\])?==([^\s;#]+)')
BUILD_VERSION = re.compile(r'cmd LC_BUILD_VERSION\n(?:.*\n)*?\s*minos (\S+)|cmd LC_VERSION_MIN_MACOSX\n(?:.*\n)*?\s*version (\S+)')


def digest(path):
    sha = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1048576), b''):
            sha.update(block)
    return sha.hexdigest()


def build_env():
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(('ROLEBAND_', 'PIP_')) and key not in {'PYTHONPATH', 'PYTHONHOME', 'VIRTUAL_ENV'}}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    return env


def unpack(archive, destination, sha):
    if digest(archive) != sha:
        raise ValueError('Standalone Python checksum mismatch')
    with tarfile.open(archive, 'r:gz') as stream:
        for member in stream.getmembers():
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'python':
                raise ValueError('Unsafe standalone Python member')
            if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
                raise ValueError('Unsupported standalone Python member')
            if member.issym() or member.islnk():
                target = posixpath.normpath(posixpath.join(str(path.parent), member.linkname) if member.issym() else member.linkname)
                if not target.startswith('python/'):
                    raise ValueError('Standalone Python link escapes its runtime')
        destination.mkdir(parents=True, exist_ok=True)
        stream.extractall(destination, filter='data')


def fetch_runtime(pin, cache):
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / (pin['sha256'] + '.tar.gz')
    if archive.is_file() and digest(archive) == pin['sha256']:
        return archive
    with tempfile.NamedTemporaryFile(dir=cache, delete=False) as staged:
        temporary = Path(staged.name)
        try:
            with urllib.request.urlopen(pin['url'], timeout=120) as response:
                shutil.copyfileobj(response, staged)
            staged.flush()
            if digest(temporary) != pin['sha256']:
                raise ValueError('Downloaded standalone Python checksum mismatch')
            temporary.replace(archive)
        finally:
            temporary.unlink(missing_ok=True)
    return archive


def export_head(root, destination, paths=HEAD_PATHS):
    """Writes the tracked files of HEAD under `paths`, so what the bundle carries is the revision its
    label names: no uncommitted edit, and no ignored file such as a log or a local database."""
    archive = subprocess.run(['git', '-C', str(root), 'archive', '--format=tar', 'HEAD', '--', *paths],
                             check=True, capture_output=True).stdout
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:
        stream.extractall(destination, filter='data')
    return destination


def source_unchanged(root, revision):
    """True while the checkout is still clean at the revision the build started from."""
    head = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'], capture_output=True, text=True)
    status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain', '--untracked-files=normal'],
                            capture_output=True, text=True)
    return head.returncode == 0 and head.stdout.strip() == revision and status.returncode == 0 and not status.stdout.strip()


def copy_engine(source, dashboard, resources):
    """`source` is an export of HEAD; `dashboard` is the built dashboard, which git does not track."""
    engine = resources / 'engine'
    engine.mkdir(parents=True, exist_ok=True)
    for name in ('tracker', 'alembic', 'constraints'):
        shutil.copytree(source / 'backend' / name, engine / name)
    for name in ('alembic.ini', 'packaged.py'):
        shutil.copyfile(source / 'backend' / name, engine / name)
    (engine / 'release.json').write_text(json.dumps({'version': release_version(source / 'dashboard/package.json')}) + '\n')
    shutil.copytree(dashboard, resources / 'dashboard', ignore=shutil.ignore_patterns('.DS_Store', DASHBOARD_DIRTY.name))
    shutil.copyfile(source / 'dashboard/csp-policy.json', resources / 'dashboard/csp-policy.json')
    shutil.copyfile(source / 'CHANGELOG.md', resources / 'CHANGELOG.md')


def copy_python_notices(archive, sha, resources):
    if digest(archive) != sha:
        raise ValueError('Python notice archive checksum mismatch')
    members = subprocess.check_output(['tar', '-tf', str(archive)], text=True).splitlines()
    selected = [name for name in members if name.startswith('python/licenses/') and not name.endswith('/')]
    if not selected or any('..' in PurePosixPath(name).parts for name in selected):
        raise ValueError('Missing or unsafe Python runtime notices')
    with tempfile.TemporaryDirectory(prefix='roleband-python-notices-') as directory:
        subprocess.run(['tar', '-xf', str(archive), '-C', directory, '--', *selected], check=True)
        source = Path(directory) / 'python/licenses'
        if any(path.is_symlink() for path in source.rglob('*')):
            raise ValueError('Python runtime notice is a symbolic link')
        target = resources / 'licenses/python-runtime'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)


def macho_files(app):
    binaries = []
    for path in app.rglob('*'):
        if path.is_file() and not path.is_symlink():
            with path.open('rb') as source:
                if source.read(4) in MACHO:
                    binaries.append(path)
    return binaries


def check_minimum_macos(app):
    # pip and native toolchains target the machine that builds, so a dependency
    # can ship a binary that the oldest supported macOS refuses to load.
    newer = []
    for path in macho_files(app):
        build = subprocess.run(['xcrun', 'vtool', '-show-build', str(path)],
                               check=True, capture_output=True, text=True).stdout
        versions = [minos or legacy for minos, legacy in BUILD_VERSION.findall(build)]
        if not versions or any(tuple(map(int, value.split('.')))[:2] > MINIMUM_MACOS for value in versions):
            newer.append(f"{path.relative_to(app)} ({', '.join(versions) or 'no version'})")
    if newer:
        raise ValueError('Binaries need a newer macOS than 14.0: ' + '; '.join(sorted(newer)[:10]))


def check_dashboard_build(root):
    """True when the dashboard was built while its source had uncommitted changes."""
    # dashboard/dist is ignored by git, so the source revision stamped into the
    # app cannot vouch for it; the build's own tree stamp has to.
    tree = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD:dashboard'],
                          capture_output=True, text=True).stdout.strip()
    stamp = root / DASHBOARD_STAMP
    built = stamp.read_text().strip() if stamp.is_file() else None
    if not tree or built != tree:
        raise ValueError('Build the dashboard from this commit with deploy/build_dashboard.sh first')
    return (root / DASHBOARD_DIRTY).exists()


def check_build_tools():
    # The notice archive is zstd-compressed; macOS tar reads it only through
    # an external zstd program.
    if shutil.which('zstd') is None:
        raise ValueError('The build needs the zstd program (brew install zstd)')


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def pinned(path):
    pins = {}
    for line in path.read_text().splitlines():
        match = REQUIREMENT.match(line.strip())
        if match:
            pins[normalized(match[1])] = match[2]
    return pins


def check_runtime_lock(root):
    lock = root / RUNTIME_LOCK
    locked = pinned(lock)
    constraints = pinned(root / 'backend/constraints/macos-arm64.txt')
    required = pinned(root / 'backend/requirements.txt')
    stale = sorted(name for name, version in locked.items() if constraints.get(name) != version)
    missing = sorted(set(required) - set(locked))
    unhashed = [line for line in lock.read_text().splitlines()
                if REQUIREMENT.match(line) and not re.search(r'--hash=sha256:[0-9a-f]{64}', line)]
    problems = stale + missing + (['a locked package has no hash'] if unhashed else [])
    if problems:
        raise ValueError('Regenerate launcher/macos/runtime-lock.txt with Tools/lock_runtime.py: ' + ', '.join(problems))
    return lock


def sign_tree(app, identity, keychain=None):
    binaries = macho_files(app)
    for path in sorted(binaries, key=lambda path: (-len(path.parts), str(path))) + [app]:
        args = ['codesign', '--force', '--timestamp=none', '--sign', identity]
        if keychain:
            args += ['--keychain', str(keychain)]
        subprocess.run([*args, str(path)], check=True)
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)


def check_size(size, previous, note):
    # Installed apps decode the note as an optional string inside a 4 KB manifest.
    if note is not None and not (isinstance(note, str) and note.strip() and len(note) <= GROWTH_NOTE_LIMIT):
        raise ValueError(f'A growth note is null or one sentence of at most {GROWTH_NOTE_LIMIT} characters')
    if previous is not None:
        if not isinstance(previous, int) or isinstance(previous, bool) or previous <= 0:
            raise ValueError('The size baseline must be a positive byte count')
        if size * 100 > previous * 115 and not (isinstance(note, str) and note.strip()):
            raise ValueError('Disk image grew more than 15%; record a growth note')


def run(command, *, env=None, cwd=ROOT):
    subprocess.run(list(map(str, command)), check=True, cwd=cwd, env=env or build_env())


def pip(python, *arguments):
    # --isolated also keeps the builder's pip configuration files out of the bundled runtime.
    run([python, '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check', *arguments])


def assemble(destination, cache, archive=None):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('Build the app on an Apple silicon Mac')
    if destination.exists():
        raise ValueError('The app destination already exists')
    check_build_tools()
    dashboard_dirty = check_dashboard_build(ROOT)
    lock = check_runtime_lock(ROOT)
    pin = json.loads((ROOT / 'launcher/macos/runtime.json').read_text())
    archive = archive or fetch_runtime(pin, cache)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bundle-', dir=destination.parent) as directory:
        head = export_head(ROOT, Path(directory) / 'head')
        app = Path(directory) / 'RoleBand.app'
        env = build_env()
        env.update(ROLEBAND_LAUNCHER_APP_PATH=str(app), ROLEBAND_LAUNCHER_DISPLAY_NAME='RoleBand',
                   ROLEBAND_LAUNCHER_BUILD_ROOT=str(cache / 'swift'))
        run([ROOT / 'launcher/macos/build-app.sh'], env=env)
        resources = app / 'Contents/Resources'
        unpack(archive, resources, pin['sha256'])
        python = resources / 'python/bin/python3.12'
        marker = resources / 'python/lib/python3.12/EXTERNALLY-MANAGED'
        marker.unlink(missing_ok=True)
        constraints = head / 'backend/constraints/macos-arm64.txt'
        pip(python, 'install', '--require-hashes', '--only-binary=:all:', '--no-deps', '-r', lock)
        wheels = resources / 'plugin-wheels'
        wheels.mkdir()
        for name in ('sdk/python', 'robots/python'):
            pip(python, 'wheel', '--no-build-isolation', '--no-deps', '--wheel-dir', wheels, head / name)
        pip(python, 'install', '--no-deps', *sorted(wheels.glob('*.whl')))
        pip(python, 'check')
        source_env = build_env()
        source_env['PYTHONPATH'] = str(head / 'backend')
        run([python, '-m', 'scripts.install_pg_contrib'], env=source_env, cwd=head / 'backend')
        run([python, '-m', 'scripts.check_source_review', '--packaged'], env=source_env, cwd=head / 'backend')
        copy_engine(head, ROOT / 'dashboard/dist', resources)
        copy_python_notices(fetch_runtime(pin['notices'], cache), pin['notices']['sha256'], resources)
        shutil.copyfile(fetch_runtime(pin['pgvector_notice'], cache), resources / 'licenses/pgvector-LICENSE')
        shutil.copyfile(resources / 'python/lib/python3.12/site-packages/pixeltable_pgserver/pginstall/share/postgresql/extension/pg_trgm.COPYRIGHT',
                        resources / 'licenses/PostgreSQL-COPYRIGHT')
        shutil.copyfile(head / 'LICENSE', resources / 'licenses/RoleBand-LICENSE')
        notices = [('--notice', name, notice['version'], fetch_runtime(notice, cache))
                   for name, notice in pin['package_notices'].items()]
        # The SDK and robots wheels are this repository's own code, under its LICENSE.
        notices += [('--notice', *wheel.name.split('-')[:2], head / 'LICENSE') for wheel in sorted(wheels.glob('*.whl'))]
        run([python, '-I', ROOT / 'launcher/macos/Tools/bundle_licenses.py', resources,
             *[part for notice in notices for part in notice]])
        run([python, '-I', '-m', 'compileall', '-q', '--invalidation-mode', 'unchecked-hash',
             '-s', resources, '-p', '/RoleBand', resources / 'python/lib/python3.12', resources / 'engine'])
        import plistlib
        info_path = app / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['RoleBandPackagedEngine'] = True
        info['RoleBandReleaseCandidate'] = True
        # The label was read before the build; a checkout that changed since, or a dashboard built
        # from uncommitted source, makes it dirty, and release.py refuses a dirty candidate.
        info['RoleBandSourceDirty'] = (info.get('RoleBandSourceDirty', True) or dashboard_dirty
                                       or not source_unchanged(ROOT, info.get('RoleBandSourceRevision')))
        info_path.write_bytes(plistlib.dumps(info))
        (resources / 'runtime.json').write_text(json.dumps({
            **pin, 'version': release_version(head / 'dashboard/package.json'),
            'requirements_sha256': digest(head / 'backend/requirements.txt'),
            'constraints_sha256': digest(constraints),
            'runtime_lock_sha256': digest(lock),
        }, indent=2) + '\n')
        check_minimum_macos(app)
        sign_tree(app, '-')
        app.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--runtime-archive', type=Path)
    args = parser.parse_args()
    print(assemble(args.destination.absolute(), args.cache.absolute(), args.runtime_archive))


if __name__ == '__main__':
    main()
