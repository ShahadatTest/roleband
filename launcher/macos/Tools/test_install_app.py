import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import install_app


def app(path, marker='new', **values):
    (path / 'Contents/MacOS').mkdir(parents=True)
    (path / 'Contents/Info.plist').write_bytes(plistlib.dumps({
        'CFBundleIdentifier': 'com.roleband.launcher', 'CFBundleExecutable': 'RoleBandLauncher', **values,
    }))
    (path / 'Contents/MacOS/RoleBandLauncher').write_text(marker)
    return path


class SourceInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = app(self.root / 'source.app')
        self.destination = self.root / 'Applications/RoleBand Launcher.app'
        self.calls = []
        self.running = install_app.running

        def run(command, **kwargs):
            self.calls.append(command)
            if command[0] == 'ditto':
                shutil.copytree(command[1], command[2])
            return subprocess.CompletedProcess(command, 0)
        self.addCleanup(patch.stopall)
        patch.object(install_app.subprocess, 'run', side_effect=run).start()
        patch.object(install_app, 'running', return_value=False).start()

    def marker(self):
        return (self.destination / 'Contents/MacOS/RoleBandLauncher').read_text()

    def test_first_install_and_closed_app_upgrade_replace_only_the_launcher_bundle(self):
        database = self.root / 'database'
        database.write_text('longitudinal record')
        install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'new')
        (self.source / 'Contents/MacOS/RoleBandLauncher').write_text('updated')
        install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'updated')
        self.assertEqual(database.read_text(), 'longitudinal record')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])
        self.assertFalse(any('xattr' in call for call in self.calls))

    def test_foreign_apps_symlinks_and_running_launchers_are_left_untouched(self):
        app(self.destination, 'original', CFBundleIdentifier='other.app')
        with self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'original')
        shutil.rmtree(self.destination)
        self.destination.symlink_to(self.source)
        with self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        self.assertTrue(self.destination.is_symlink())
        self.destination.unlink()
        app(self.destination, 'original')
        with patch.object(install_app, 'running', return_value=True), self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'original')

    def test_preview_and_bad_signatures_cannot_replace_the_installed_app(self):
        app(self.destination, 'original')
        info = self.source / 'Contents/Info.plist'
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.roleband.launcher',
            'CFBundleExecutable': 'RoleBandLauncher', 'RoleBandRegistration': '/temporary/installation.json'}))
        with self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.roleband.launcher', 'CFBundleExecutable': 'RoleBandLauncher'}))
        with patch.object(install_app.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'codesign')):
            with self.assertRaises(subprocess.CalledProcessError):
                install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'original')

    def test_an_app_opened_during_staging_prevents_replacement(self):
        app(self.destination, 'original')
        with patch.object(install_app, 'running', side_effect=[False, True]), self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'original')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_a_demo_feed_alone_cannot_be_source_installed(self):
        info_path = self.source / 'Contents/Info.plist'
        info = plistlib.loads(info_path.read_bytes())
        info['RoleBandDemoReleaseFile'] = '/temporary/release.json'
        info_path.write_bytes(plistlib.dumps(info))
        with self.assertRaises(ValueError):
            install_app.install(self.source, self.destination)
        self.assertFalse(self.destination.exists())

    def test_publication_failure_restores_the_previous_app(self):
        app(self.destination, 'original')
        rename = Path.rename
        def fail_staging(path, target):
            if path.name == self.destination.name and path.parent.name.startswith('.roleband-install-'):
                raise OSError('fixture publication failure')
            return rename(path, target)
        with patch.object(Path, 'rename', fail_staging), self.assertRaises(OSError):
            install_app.install(self.source, self.destination)
        self.assertEqual(self.marker(), 'original')
        self.assertEqual(list(self.destination.parent.iterdir()), [self.destination])

    def test_process_guard_matches_the_exact_executable_path(self):
        path = str(self.destination.resolve() / 'Contents/MacOS/RoleBandLauncher')
        with patch.object(install_app.subprocess, 'check_output', return_value=path + ' other\n'):
            self.assertFalse(self.running(self.destination))
        with patch.object(install_app.subprocess, 'check_output', return_value=path + '\n'):
            self.assertTrue(self.running(self.destination))


class LauncherOfferTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'deploy').mkdir()
        script = Path(__file__).resolve().parents[3] / 'deploy/offer_launcher.sh'
        shutil.copy2(script, self.root / 'deploy/offer_launcher.sh')
        tools = self.root / 'bin'
        tools.mkdir()
        compiler = tools / 'xcrun'
        compiler.write_text('#!/bin/sh\nexit "${NO_SWIFT:-0}"\n')
        compiler.chmod(0o755)
        launcher = self.root / 'launcher/macos/install.sh'
        launcher.parent.mkdir(parents=True)
        self.record = self.root / 'attempted'
        launcher.write_text(f'#!/bin/sh\ntouch "{self.record}"\nexit 0\n')
        launcher.chmod(0o755)

    def run_offer(self, **extra):
        import os
        environment = {**os.environ, 'HOME': str(self.root / 'home'),
            'PATH': f'{self.root / "bin"}:{os.environ["PATH"]}', 'ROLEBAND_INSTALL_LAUNCHER': 'ask', **extra}
        return subprocess.run(['bash', str(self.root / 'deploy/offer_launcher.sh')], input='',
            text=True, capture_output=True, env=environment, check=True)

    def test_noninteractive_default_never_builds_and_names_the_later_install_command(self):
        result = self.run_offer()
        self.assertFalse(self.record.exists())
        self.assertIn('launcher/macos/install.sh', result.stdout)

    def test_explicit_skip_and_missing_toolchain_leave_no_launcher(self):
        self.run_offer(ROLEBAND_INSTALL_LAUNCHER='no')
        result = self.run_offer(ROLEBAND_INSTALL_LAUNCHER='yes', NO_SWIFT='1')
        self.assertIn('Command Line Tools', result.stdout)
        self.assertFalse(self.record.exists())

    def test_explicit_opt_in_runs_the_source_installer(self):
        self.run_offer(ROLEBAND_INSTALL_LAUNCHER='yes')
        self.assertTrue(self.record.exists())


if __name__ == '__main__':
    unittest.main()
