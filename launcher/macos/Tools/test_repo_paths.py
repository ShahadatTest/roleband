import ast
import os
import subprocess
import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent

# Every sibling tool except the path module is replaced by an empty stand-in, so
# the module under test can reach `tracker` only through a path it set itself.
ISOLATED_IMPORT = '''
import sys, types

class StandIn(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)
        return None

tools, module, *siblings = sys.argv[1:]
sys.path.insert(0, tools)
for name in siblings:
    sys.modules[name] = StandIn(name)
__import__(module)
import tracker
print(tracker.__file__)
'''


def imports_tracker(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import) and any(alias.name.split('.')[0] == 'tracker' for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or '').split('.')[0] == 'tracker':
            return True
    return False


class RepoPathTests(unittest.TestCase):
    def test_each_tool_that_imports_the_backend_sets_its_own_path(self):
        tools = sorted(path for path in TOOLS.glob('*.py') if not path.name.startswith('test_'))
        importers = [path.stem for path in tools if imports_tracker(path)]
        self.assertIn('bundle', importers)
        self.assertIn('release', importers)
        backend = TOOLS.parents[2] / 'backend'
        env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH', 'PYTHONHOME'}}
        for module in importers:
            siblings = [path.stem for path in tools if path.stem not in {module, 'repo_paths'}]
            with self.subTest(module=module):
                result = subprocess.run([sys.executable, '-I', '-c', ISOLATED_IMPORT, str(TOOLS), module, *siblings],
                                        capture_output=True, text=True, env=env, cwd=TOOLS.parent, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(Path(result.stdout.strip()).parent.parent, backend)

    def test_the_root_is_this_repository_and_the_backend_is_added_once(self):
        import repo_paths

        self.assertTrue((repo_paths.ROOT / 'launcher/macos/Tools/repo_paths.py').is_file())
        self.assertEqual(repo_paths.BACKEND, repo_paths.ROOT / 'backend')
        self.assertEqual(sys.path.count(str(repo_paths.BACKEND)), 1)


if __name__ == '__main__':
    unittest.main()
