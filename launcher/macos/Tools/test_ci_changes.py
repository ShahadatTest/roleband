import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ci_changes import decide, glob_regex, needed

TOOLS = Path(__file__).resolve().parent
NATIVE = ['launcher/**', 'dashboard/src/copy/**', '.nvmrc']
BUNDLE = ['backend/packaged.py', 'backend/constraints/**']


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True, text=True).stdout.strip()


class TierTests(unittest.TestCase):
    def test_a_pull_request_runs_the_native_tests_only_when_a_watched_file_changed(self):
        self.assertEqual(decide('pull_request', ['dashboard/src/features/Board.tsx', 'backend/tracker/api/app.py'],
                                NATIVE, BUNDLE), {'native': False, 'bundle': False})
        self.assertEqual(decide('pull_request', ['dashboard/src/copy/en/launcher.ftl'], NATIVE, BUNDLE),
                         {'native': True, 'bundle': False})

    def test_a_pull_request_never_builds_the_bundle(self):
        self.assertEqual(decide('pull_request', ['backend/packaged.py', 'launcher/macos/Package.swift'], NATIVE, BUNDLE),
                         {'native': True, 'bundle': False})

    def test_a_push_builds_the_bundle_for_its_own_inputs_and_the_native_tests_with_it(self):
        self.assertEqual(decide('push', ['backend/constraints/macos-arm64.txt'], NATIVE, BUNDLE),
                         {'native': True, 'bundle': True})
        self.assertEqual(decide('push', ['launcher/macos/Sources/RoleBandLauncher/Main.swift'], NATIVE, BUNDLE),
                         {'native': True, 'bundle': True})
        self.assertEqual(decide('push', ['docs/ui.md'], NATIVE, BUNDLE), {'native': False, 'bundle': False})

    def test_what_cannot_be_judged_runs_everything(self):
        for event in ('release', 'workflow_dispatch', 'schedule'):
            self.assertEqual(decide(event, [], NATIVE, BUNDLE), {'native': True, 'bundle': True})
        self.assertEqual(decide('push', None, NATIVE, BUNDLE), {'native': True, 'bundle': True})

    def test_a_single_tier_is_skipped_only_by_a_pull_request_that_misses_it(self):
        backend = ['backend/**', '.python-version']
        self.assertFalse(needed('pull_request', ['docs/testing.md', '.coderabbit.yaml'], backend))
        self.assertTrue(needed('pull_request', ['docs/testing.md', 'backend/tracker/api/app.py'], backend))
        self.assertTrue(needed('pull_request', None, backend))
        for event in ('push', 'release', 'workflow_dispatch', 'schedule'):
            self.assertTrue(needed(event, ['docs/testing.md'], backend), event)

    def test_globs_follow_github(self):
        self.assertTrue(glob_regex('launcher/**').fullmatch('launcher/macos/Tools/bundle.py'))
        self.assertFalse(glob_regex('backend/*').fullmatch('backend/tracker/api/app.py'))
        self.assertTrue(glob_regex('backend/*').fullmatch('backend/requirements.txt'))
        self.assertFalse(glob_regex('.nvmrc').fullmatch('x.nvmrc'))


class WorkflowStepTests(unittest.TestCase):
    """The script as the workflow runs it: a real repository, a real diff, GITHUB_OUTPUT."""

    def run_step(self, repo, event, base, head, tier=None):
        with tempfile.NamedTemporaryFile('r', suffix='.txt') as output:
            env = {**os.environ, 'EVENT': event, 'BASE': base, 'HEAD': head, 'GITHUB_OUTPUT': output.name}
            if tier:
                env.update(TIER=tier, PATHS='backend/**\n')
            else:
                env.update(NATIVE_PATHS='\n'.join(NATIVE) + '\n', BUNDLE_PATHS='\n'.join(BUNDLE) + '\n')
            subprocess.run([sys.executable, str(TOOLS / 'ci_changes.py')], cwd=repo, env=env, check=True,
                           capture_output=True)
            return dict(line.split('=') for line in output.read().split())

    def test_the_step_reads_the_diff_between_the_two_commits(self):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, 'init', '-q')
            git(repo, 'config', 'user.email', 'ci@example.test')
            git(repo, 'config', 'user.name', 'CI')
            Path(repo, 'notes').mkdir()
            Path(repo, 'notes/a.txt').write_text('a\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'notes')
            base = git(repo, 'rev-parse', 'HEAD')
            Path(repo, 'notes/a.txt').write_text('b\n')
            git(repo, 'commit', '-qam', 'notes again')
            notes = git(repo, 'rev-parse', 'HEAD')
            Path(repo, 'backend').mkdir()
            Path(repo, 'backend/packaged.py').write_text('x = 1\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '-qm', 'entry point')
            entry = git(repo, 'rev-parse', 'HEAD')

            self.assertEqual(self.run_step(repo, 'push', base, notes), {'native': 'false', 'bundle': 'false'})
            self.assertEqual(self.run_step(repo, 'push', notes, entry), {'native': 'true', 'bundle': 'true'})
            self.assertEqual(self.run_step(repo, 'pull_request', base, entry), {'native': 'false', 'bundle': 'false'})
            self.assertEqual(self.run_step(repo, 'push', '0' * 40, entry), {'native': 'true', 'bundle': 'true'})
            self.assertEqual(self.run_step(repo, 'push', 'f' * 40, entry), {'native': 'true', 'bundle': 'true'})

            self.assertEqual(self.run_step(repo, 'pull_request', base, notes, 'backend'), {'backend': 'false'})
            self.assertEqual(self.run_step(repo, 'pull_request', base, entry, 'backend'), {'backend': 'true'})
            self.assertEqual(self.run_step(repo, 'push', base, notes, 'backend'), {'backend': 'true'})
            self.assertEqual(self.run_step(repo, 'pull_request', 'f' * 40, notes, 'backend'), {'backend': 'true'})


if __name__ == '__main__':
    unittest.main()
