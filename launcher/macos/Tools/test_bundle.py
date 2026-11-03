import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import bundle
except ImportError:
    bundle = None


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bundle, 'the standalone bundle builder is missing')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, name='python/bin/python3.12', link=None):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as archive:
            member = tarfile.TarInfo(name)
            if link is not None:
                member.type = tarfile.SYMTYPE
                member.linkname = link
                archive.addfile(member)
            else:
                data = b'standalone runtime'
                member.mode = 0o755
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        path = self.root / 'python.tar.gz'
        path.write_bytes(stream.getvalue())
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    def test_verified_runtime_extracts_with_executable_mode_and_bad_digest_writes_nothing(self):
        archive, sha = self.archive()
        with self.assertRaises(ValueError):
            bundle.unpack(archive, self.root / 'bad', '0' * 64)
        self.assertFalse((self.root / 'bad').exists())
        bundle.unpack(archive, self.root / 'resources', sha)
        self.assertTrue(os.access(self.root / 'resources/python/bin/python3.12', os.X_OK))

    def test_runtime_archive_refuses_traversal_and_outside_symlinks(self):
        for name, link in [('python/../../outside', None), ('python/bin/python', '../../../outside')]:
            with self.subTest(name=name, link=link):
                archive, sha = self.archive(name, link)
                with self.assertRaises(ValueError):
                    bundle.unpack(archive, self.root / 'resources', sha)
                self.assertFalse((self.root / 'outside').exists())

    def test_engine_copy_carries_heads_files_and_never_an_edit_or_an_ignored_file(self):
        repo = self.root / 'repo'
        for name in ('backend/tracker/__init__.py', 'backend/alembic/env.py', 'backend/alembic.ini',
                     'backend/packaged.py', 'backend/constraints/macos-arm64.txt',
                     'dashboard/csp-policy.json', 'CHANGELOG.md', 'LICENSE', 'sdk/python/pyproject.toml',
                     'robots/python/pyproject.toml'):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('committed')
        (repo / 'dashboard/package.json').write_text('{"version":"1.2.3-rc.1"}')
        (repo / '.gitignore').write_text('dashboard/dist/\n*.log\ndata/\n.env\n__pycache__/\n.venv/\n')
        self.git(repo, 'init', '-q')
        self.git(repo, 'add', '.')
        self.git(repo, 'commit', '-qm', 'base')
        (repo / 'backend/tracker/__init__.py').write_text('an uncommitted edit')
        (repo / 'backend/tracker/new_module.py').write_text('untracked')
        for name in ('backend/.env', 'backend/tracker/scan.log', 'backend/tracker/data/roleband.db',
                     'backend/tracker/__pycache__/old.pyc', 'backend/tracker/.venv/private'):
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('local')
        dist = repo / 'dashboard/dist'
        dist.mkdir(parents=True)
        (dist / 'index.html').write_text('built')
        (dist / '.roleband-dirty').write_text('')
        head = bundle.export_head(repo, self.root / 'head')
        destination = self.root / 'resources'
        bundle.copy_engine(head, dist, destination)
        self.assertEqual(json.loads((destination / 'engine/release.json').read_text()), {'version':'1.2.3-rc.1'})
        self.assertEqual((destination / 'engine/tracker/__init__.py').read_text(), 'committed')
        self.assertEqual(sorted(path.name for path in (destination / 'engine').rglob('*') if path.is_file()),
                         ['__init__.py', 'alembic.ini', 'env.py', 'macos-arm64.txt', 'packaged.py', 'release.json'])
        self.assertEqual((destination / 'dashboard/index.html').read_text(), 'built')
        self.assertTrue((destination / 'dashboard/csp-policy.json').is_file())
        self.assertFalse((destination / 'dashboard/.roleband-dirty').exists())
        self.assertTrue((head / 'sdk/python/pyproject.toml').is_file() and (head / 'LICENSE').is_file())

    def test_the_label_stays_clean_only_while_the_checkout_is_clean_at_the_same_revision(self):
        repo = self.root / 'repo'
        repo.mkdir()
        (repo / 'file').write_text('one')
        self.git(repo, 'init', '-q')
        self.git(repo, 'add', 'file')
        self.git(repo, 'commit', '-qm', 'one')
        revision = self.git(repo, 'rev-parse', 'HEAD')
        self.assertTrue(bundle.source_unchanged(repo, revision))
        (repo / 'file').write_text('edited during the build')
        self.assertFalse(bundle.source_unchanged(repo, revision))
        self.git(repo, 'commit', '-qam', 'two')
        self.assertFalse(bundle.source_unchanged(repo, revision))
        self.assertFalse(bundle.source_unchanged(repo, 'unknown'))

    def test_inside_out_signing_covers_extensionless_macho_and_stops_on_a_failed_child(self):
        app = self.root / 'RoleBand.app'
        for path in ('Contents/MacOS/RoleBandLauncher', 'Contents/Resources/python/bin/python3.12',
                     'Contents/Resources/python/lib/ext.so'):
            file = app / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'\xcf\xfa\xed\xfe' + b'fixture')
        calls=[]
        with patch.object(bundle.subprocess, 'run', side_effect=lambda args, **kw: calls.append(args)):
            bundle.sign_tree(app, 'test-identity', self.root / 'test.keychain')
        signed = [Path(call[-1]) for call in calls if '--sign' in call]
        self.assertEqual(set(signed), set(app.rglob('ext.so')) | set(app.rglob('python3.12')) | {app / 'Contents/MacOS/RoleBandLauncher', app})
        self.assertEqual(signed[-1], app)
        self.assertIn(['codesign', '--verify', '--deep', '--strict', str(app)], calls)
        with patch.object(bundle.subprocess, 'run', side_effect=OSError('sign failed')):
            with self.assertRaises(OSError):
                bundle.sign_tree(app, 'test-identity', self.root / 'test.keychain')

    def test_size_growth_requires_a_note_and_first_release_records_without_inventing_a_baseline(self):
        bundle.check_size(115, 100, None)
        bundle.check_size(1000, None, None)
        with self.assertRaises(ValueError):
            bundle.check_size(116, 100, None)
        bundle.check_size(116, 100, 'The runtime adds a required package.')
        bundle.check_size(100, 100, 'x' * 280)
        for note in [{'text': 'The runtime adds a package.'}, ['why'], 7, True, '', '   ', 'x' * 281]:
            for previous in (None, 100):
                with self.subTest(note=note, previous=previous), self.assertRaises(ValueError):
                    bundle.check_size(100, previous, note)

    def test_build_environment_does_not_inherit_an_engine_database_or_python_path(self):
        with patch.dict(os.environ, {'ROLEBAND_PGDATA':'/live/db', 'PYTHONPATH':'/another/checkout',
                                     'PYTHONHOME':'/another/python', 'ROLEBAND_PACKAGED':'1',
                                     'PIP_REQUIRE_VIRTUALENV': '1', 'PIP_INDEX_URL': 'https://mirror.invalid/simple'}):
            env=bundle.build_env()
        self.assertNotIn('ROLEBAND_PGDATA', env)
        self.assertNotIn('ROLEBAND_PACKAGED', env)
        self.assertNotIn('PYTHONPATH', env)
        self.assertNotIn('PYTHONHOME', env)
        self.assertNotIn('PIP_REQUIRE_VIRTUALENV', env)
        self.assertNotIn('PIP_INDEX_URL', env)
        self.assertEqual(env['PYTHONDONTWRITEBYTECODE'], '1')

    def test_the_builds_pip_ignores_the_builders_own_pip_configuration(self):
        home = self.root / 'home'
        for folder in ('.config/pip', 'Library/Application Support/pip', '.pip'):
            (home / folder).mkdir(parents=True)
            (home / folder / 'pip.conf').write_text('[list]\nformat = not-a-format\n')
        with patch.dict(os.environ, {'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config')}):
            with self.assertRaises(subprocess.CalledProcessError):
                bundle.run([sys.executable, '-I', '-m', 'pip', 'list'])
            bundle.pip(sys.executable, 'list')

    def test_python_native_notices_are_extracted_without_copying_the_full_runtime_build(self):
        archive, sha = self.archive('python/licenses/LICENSE.openssl-3.txt')
        resources = self.root / 'resources'
        bundle.copy_python_notices(archive, sha, resources)
        self.assertEqual((resources / 'licenses/python-runtime/LICENSE.openssl-3.txt').read_bytes(), b'standalone runtime')
        self.assertFalse((resources / 'python').exists())

    def git(self, repo, *args):
        return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test', '-c', 'user.email=test@example.com',
                               '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, text=True).stdout.strip()

    def test_only_a_dashboard_stamped_with_this_commits_tree_is_bundled(self):
        repo = self.root / 'repo'
        (repo / 'dashboard').mkdir(parents=True)
        (repo / 'dashboard/package.json').write_text('{"version":"0.1.0"}')
        self.git(repo, 'init', '-q')
        self.git(repo, 'add', 'dashboard/package.json')
        self.git(repo, 'commit', '-qm', 'dashboard')
        first = self.git(repo, 'rev-parse', 'HEAD:dashboard')
        with self.assertRaises(ValueError):
            bundle.check_dashboard_build(repo)
        (repo / 'dashboard/dist').mkdir()
        (repo / 'dashboard/dist/.roleband-tree').write_text(first + '\n')
        self.assertFalse(bundle.check_dashboard_build(repo))
        (repo / 'dashboard/dist/.roleband-dirty').write_text('')
        self.assertTrue(bundle.check_dashboard_build(repo), 'a build from uncommitted source passed as clean')
        (repo / 'dashboard/package.json').write_text('{"version":"0.2.0"}')
        self.git(repo, 'commit', '-qam', 'next version')
        with self.assertRaises(ValueError):
            bundle.check_dashboard_build(repo)

    def lock_fixture(self, lock, requirements='alpha[extra]==1.0  # core\nbeta==2.0\n'):
        (self.root / 'launcher/macos').mkdir(parents=True, exist_ok=True)
        (self.root / 'backend/constraints').mkdir(parents=True, exist_ok=True)
        (self.root / 'backend/requirements.txt').write_text(requirements)
        (self.root / 'backend/constraints/macos-arm64.txt').write_text('alpha==1.0\nbeta==2.0\ngamma==3.0\npytest==9.0\n')
        (self.root / 'launcher/macos/runtime-lock.txt').write_text('# header\n' + lock)

    def test_runtime_lock_must_hash_every_package_and_agree_with_the_constraints(self):
        bundle.check_runtime_lock(bundle.ROOT)
        hashed = ' --hash=sha256:' + 'a' * 64
        good = f'alpha==1.0{hashed}\nbeta==2.0{hashed}\ngamma==3.0{hashed}\n'
        self.lock_fixture(good)
        bundle.check_runtime_lock(self.root)
        for name, lock in [('stale version', good.replace('gamma==3.0', 'gamma==3.1')),
                           ('missing requirement', f'alpha==1.0{hashed}\ngamma==3.0{hashed}\n'),
                           ('no hash', good.replace('beta==2.0' + hashed, 'beta==2.0'))]:
            with self.subTest(name):
                self.lock_fixture(lock)
                with self.assertRaises(ValueError):
                    bundle.check_runtime_lock(self.root)

    def test_binaries_that_need_a_macos_newer_than_14_are_refused(self):
        app = self.root / 'RoleBand.app'
        library = app / 'Contents/Resources/python/lib'
        library.mkdir(parents=True)
        source = self.root / 'probe.c'
        source.write_text('int roleband_probe(void) { return 1; }\n')
        for name, version in [('old.dylib', '11.0'), ('oldest-supported.dylib', '14.0')]:
            subprocess.run(['xcrun', 'clang', '-dynamiclib', '-arch', 'arm64', f'-mmacosx-version-min={version}',
                            str(source), '-o', str(library / name)], check=True)
        (library / 'notice.txt').write_text('not a binary')
        bundle.check_minimum_macos(app)
        subprocess.run(['xcrun', 'clang', '-dynamiclib', '-arch', 'arm64', '-mmacosx-version-min=15.0',
                        str(source), '-o', str(library / 'newer.dylib')], check=True)
        with self.assertRaises(ValueError) as refused:
            bundle.check_minimum_macos(app)
        self.assertIn('newer.dylib (15.0)', str(refused.exception))
        self.assertNotIn('old.dylib', str(refused.exception))

    def test_build_without_zstd_stops_before_any_work(self):
        destination = self.root / 'out/RoleBand.app'
        with patch.object(bundle.shutil, 'which', return_value=None), \
                patch.object(bundle.subprocess, 'run') as command, patch.object(bundle, 'fetch_runtime') as fetch:
            with self.assertRaises(ValueError) as refused:
                bundle.assemble(destination, self.root / 'cache')
        self.assertIn('zstd', str(refused.exception))
        command.assert_not_called()
        fetch.assert_not_called()
        self.assertFalse((self.root / 'out').exists())

    def test_a_build_only_makes_the_candidate_and_leaves_release_signing_to_the_seal(self):
        destination, cache = self.root / 'RoleBand.app', self.root / 'cache'
        with patch.object(bundle, 'assemble') as assemble, \
                patch.object(sys, 'argv', ['bundle.py', str(destination), '--cache', str(cache)]):
            bundle.main()
        assemble.assert_called_once_with(destination, cache, None)
        for option in (['--identity', 'Developer'], ['--release-public-key', str(self.root / 'release-public.pem')],
                       ['--keychain', str(self.root / 'build.keychain')]):
            with self.subTest(option=option[0]):
                with patch.object(bundle, 'assemble') as assemble, contextlib.redirect_stderr(io.StringIO()), \
                        patch.object(sys, 'argv', ['bundle.py', str(destination), '--cache', str(cache), *option]):
                    with self.assertRaises(SystemExit) as refused:
                        bundle.main()
                self.assertEqual(refused.exception.code, 2)
                assemble.assert_not_called()


if __name__ == '__main__':
    unittest.main()
