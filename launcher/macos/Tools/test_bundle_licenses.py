import importlib.metadata
import json
import re
import tempfile
import unittest
from pathlib import Path

try:
    import bundle_licenses
except ImportError:
    bundle_licenses = None

MACOS = Path(__file__).resolve().parents[1]


def install(root, name, version, notice=None, license='Apache-2.0'):
    info = root / f'{name.replace("-", "_")}-{version}.dist-info'
    info.mkdir()
    (info / 'METADATA').write_text(f'Metadata-Version: 2.4\nName: {name}\nVersion: {version}\nLicense-Expression: {license}\n')
    record = [f'{info.name}/METADATA,,']
    if notice is not None:
        (info / 'LICENSE').write_text(notice)
        record.append(f'{info.name}/LICENSE,,')
    (info / 'RECORD').write_text('\n'.join(record) + '\n')


def installed(root):
    return list(importlib.metadata.distributions(path=[str(root)]))


class LicenseInventoryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bundle_licenses, 'the runtime notice collector is missing')
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__('shutil').rmtree, self.root)
        self.resources = self.root / 'resources'
        self.upstream = self.root / 'upstream-LICENSE'
        self.upstream.write_text('upstream licence text')

    def test_inventory_copies_metadata_notices(self):
        install(self.root, 'fixture-pkg', '1.0', notice='fixture license text', license='MIT')
        rows = bundle_licenses.generate(self.resources, installed(self.root))
        self.assertEqual([row['name'] for row in rows], ['fixture-pkg'])
        self.assertEqual(rows[0]['license'], 'MIT')
        copied = self.resources / 'licenses' / rows[0]['notices'][0]['path']
        self.assertEqual(copied.read_text(), 'fixture license text')
        self.assertEqual(json.loads((self.resources / 'licenses/python-packages.json').read_text()), rows)

    def test_a_package_that_ships_no_licence_text_fails_the_build_naming_it(self):
        install(self.root, 'fixture-pkg', '1.0', notice='fixture license text')
        install(self.root, 'silent-pkg', '2.0')
        with self.assertRaisesRegex(ValueError, r'silent-pkg 2\.0 ships no licence text') as raised:
            bundle_licenses.generate(self.resources, installed(self.root))
        self.assertNotIn('fixture-pkg', str(raised.exception))
        self.assertFalse((self.resources / 'licenses/python-packages.json').exists())

    def test_a_pinned_notice_fills_in_for_a_package_that_ships_none(self):
        install(self.root, 'silent-pkg', '2.0')
        rows = bundle_licenses.generate(self.resources, installed(self.root),
                                        pinned=[('silent_pkg', '2.0', self.upstream)])
        [notice] = rows[0]['notices']
        self.assertEqual(notice['source'], 'pinned')
        self.assertEqual((self.resources / 'licenses' / notice['path']).read_text(), 'upstream licence text')

    def test_a_pinned_notice_for_another_version_fails(self):
        install(self.root, 'silent-pkg', '2.1')
        with self.assertRaisesRegex(ValueError, r'silent-pkg is for 2\.0, but 2\.1 is installed'):
            bundle_licenses.generate(self.resources, installed(self.root), pinned=[('silent-pkg', '2.0', self.upstream)])

    def test_a_pinned_notice_that_fills_no_gap_fails(self):
        install(self.root, 'fixture-pkg', '1.0', notice='fixture license text')
        pins = [('fixture-pkg', '1.0', self.upstream), ('absent-pkg', '1.0', self.upstream)]
        with self.assertRaises(ValueError) as raised:
            bundle_licenses.generate(self.resources, installed(self.root), pinned=pins)
        self.assertRegex(str(raised.exception), r'fixture-pkg fills no gap: it ships its own licence text')
        self.assertRegex(str(raised.exception), r'absent-pkg fills no gap: it is not installed')


class RuntimePinTests(unittest.TestCase):
    def test_each_pinned_package_notice_matches_the_locked_version(self):
        locked = dict(re.findall(r'^([A-Za-z0-9_.-]+)==(\S+)', (MACOS / 'runtime-lock.txt').read_text(), re.M))
        locked = {name.lower(): version for name, version in locked.items()}
        pins = json.loads((MACOS / 'runtime.json').read_text())['package_notices']
        self.assertTrue({'flatbuffers', 'tokenizers'} <= set(pins), 'both wheels ship without their licence text')
        for name, pin in pins.items():
            self.assertEqual(pin['version'], locked.get(name), f'{name} is locked at another version; re-pin its notice')
            self.assertIn(f'/v{pin["version"]}/', pin['url'], f'{name} notice is read from another release')
            self.assertRegex(pin['sha256'], r'^[0-9a-f]{64}$')


if __name__ == '__main__':
    unittest.main()
