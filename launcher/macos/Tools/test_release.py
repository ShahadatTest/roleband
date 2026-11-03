import base64
import hashlib
import json
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bundle
import release
import signing
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

COMMIT = 'a' * 40
PASSPHRASE, CERTIFICATE_PASSWORD = b'release passphrase', b'certificate password'


def protected(keys, name='RoleBand'):
    """A release identity as the maintainer makes it: the spare apart, every key behind a password."""
    signing.generate(keys, name, spare_directory=keys.with_name(keys.name + '-spare'),
                     passphrase=PASSPHRASE, certificate_password=CERTIFICATE_PASSWORD)


class ReleaseAssetTests(unittest.TestCase):
    def test_native_verifier_fixture_uses_the_current_release_protocol(self):
        path = Path(__file__).resolve().parents[1] / 'Tests/LauncherCoreTests/Fixtures/update-artifact.json'
        fixture = {key: base64.b64decode(value, validate=True) for key, value in json.loads(path.read_text()).items()}
        private = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        sha = hashlib.sha256(fixture['image']).hexdigest()
        metadata = (json.dumps(release.manifest('0.1.1', COMMIT, sha, len(fixture['image']), public, None, None), indent=2) + '\n').encode()
        checksum = f'{sha}  RoleBand-0.1.1-macOS-arm64.dmg\n'.encode()
        self.assertEqual(fixture['publicKey'], public)
        self.assertEqual(fixture['metadata'], metadata)
        self.assertEqual(fixture['checksum'], checksum)
        self.assertEqual(fixture['signature'], private.sign(checksum + metadata))

    def test_native_notice_fixture_is_the_tools_format_3_bytes(self):
        path = Path(__file__).resolve().parents[1] / 'Tests/LauncherCoreTests/Fixtures/update-artifact-notice.json'
        fixture = {key: base64.b64decode(value, validate=True) for key, value in json.loads(path.read_text()).items()}
        private = ed25519.Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        sha = hashlib.sha256(fixture['image']).hexdigest()
        notice = 'This version moves your radar to a new storage format. A backup is made first.'
        metadata = (json.dumps(release.manifest('0.1.1', COMMIT, sha, len(fixture['image']), public, None, None, notice),
                               indent=2) + '\n').encode()
        self.assertEqual(fixture['metadata'], metadata)
        self.assertEqual(fixture['signature'], private.sign(fixture['checksum'] + metadata))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'dashboard').mkdir()
        (self.root / 'dashboard/package.json').write_text('{"version":"0.1.0"}')
        baseline = self.root / 'launcher/macos/bundle-size.json'
        baseline.parent.mkdir(parents=True)
        baseline.write_text('{"previous_release_dmg_bytes":null,"growth_note":null}')
        keys = self.root / 'keys'
        protected(keys, 'RoleBand CI Trial')
        self.signing_key = keys / 'release-private.pem'
        (self.root / 'launcher/macos/release-identity.json').write_text('{"certificate_sha256": null, "release_public_key": null}')
        signing.record(keys, self.root)
        self.public_key = keys / 'release-public.pem'
        self.certificate = signing.load_certificate(keys)
        public = serialization.load_pem_public_key(self.public_key.read_bytes()).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.spare = json.loads((self.root / 'launcher/macos/release-identity.json').read_text())['spare_release_public_key']
        self.app = self.root / 'RoleBand.app'
        (self.app / 'Contents/MacOS').mkdir(parents=True)
        (self.app / 'Contents/Info.plist').write_bytes(plistlib.dumps({
            'CFBundleIdentifier': 'com.roleband.launcher', 'CFBundleExecutable': 'RoleBandLauncher',
            'CFBundleName': 'RoleBand', 'CFBundleDisplayName': 'RoleBand', 'LSUIElement': True,
            'RoleBandVersion': '0.1.0', 'CFBundleShortVersionString': '0.1.0', 'CFBundleVersion': '0.1.0',
            'RoleBandSourceRevision': COMMIT, 'RoleBandSourceDirty': False,
            'LSMinimumSystemVersion': '14.0',
            'RoleBandPackagedEngine': True, 'RoleBandSigningIdentity': (keys / 'identity').read_text(),
            'RoleBandUpdatePublicKey': base64.b64encode(public).decode(),
            'RoleBandUpdateSpareKey': self.spare,
            'RoleBandUpdateRequirement': f'certificate leaf = H"{(keys / 'identity').read_text()}"',
            'RoleBandUpdateFeed': 'roleband/roleband',
        }))
        self.destination = self.root / 'distribution'
        self.calls = []
        self.dirty = False
        self.remote_commit = COMMIT
        self.draft = False
        self.architecture = 'arm64'
        self.prerelease = False

        def output(command, **kwargs):
            self.calls.append(command)
            if command[:3] == ['git', 'rev-parse', 'HEAD']:
                return COMMIT
            if command[:2] == ['git', 'status']:
                return ' M changed.file' if self.dirty else ''
            if command[0] == 'lipo':
                return self.architecture
            if command[:3] == ['xcrun', 'vtool', '-show-build']:
                return 'platform MACOS\nminos 14.0\nsdk 26.0'
            if command[:3] == ['gh', 'release', 'view']:
                return json.dumps({'tagName': command[3], 'isDraft': self.draft, 'isPrerelease': self.prerelease})
            if command[:2] == ['gh', 'api']:
                return self.remote_commit
            raise AssertionError(command)

        def run(command, **kwargs):
            self.calls.append(command)
            if command[0].endswith('make-dmg.sh'):
                Path(command[-1]).write_bytes(b'fixture disk image')
            if '--extract-certificates' in command:
                raise subprocess.CalledProcessError(1, command, stderr='Optional long arguments require =')
            for argument in command:
                if argument.startswith('--extract-certificates='):
                    Path(argument.split('=', 1)[1] + '0').write_bytes(self.certificate.public_bytes(serialization.Encoding.DER))
            return subprocess.CompletedProcess(command, 0, stderr='Authority=RoleBand CI Trial\n')
        self.addCleanup(patch.stopall)
        patch.object(release, 'output', side_effect=output).start()
        patch.object(release.subprocess, 'run', side_effect=run).start()

    def prepare(self):
        return release.prepare(self.app, self.destination, 'v0.1.0', self.root, signing_key=self.signing_key,
                               passphrase=PASSPHRASE)

    def test_candidate_image_is_explicitly_unsigned_for_release_and_cannot_be_uploaded(self):
        path = self.app / 'Contents/Info.plist'
        info = plistlib.loads(path.read_bytes())
        info.pop('RoleBandSigningIdentity')
        info.pop('RoleBandUpdatePublicKey')
        info['RoleBandReleaseCandidate'] = True
        for sealed in ('RoleBandUpdateSpareKey', 'RoleBandUpdateRequirement', 'RoleBandUpdateFeed'):
            path.write_bytes(plistlib.dumps(info))
            with self.subTest(sealed), self.assertRaises(ValueError):
                release.candidate(self.app, self.destination, self.root)
            self.assertFalse(self.destination.exists())
            info.pop(sealed)
        path.write_bytes(plistlib.dumps(info))
        release.candidate(self.app, self.destination, self.root)
        metadata = json.loads((self.destination / 'candidate.json').read_text())
        image = self.destination / metadata['image']
        self.assertFalse(metadata['release_ready'])
        self.assertEqual(metadata['signing'], 'ad-hoc')
        self.assertEqual(metadata['commit'], COMMIT)
        self.assertEqual(metadata['sha256'], hashlib.sha256(image.read_bytes()).hexdigest())
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertFalse(any(call[0] == 'gh' for call in self.calls))

    def test_image_checksum_and_source_identity_are_published_together_then_verified_before_upload(self):
        self.prepare()
        files = release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)
        self.assertEqual(len(files), 4)
        self.assertEqual(json.loads(files[2].read_text())['sha256'], hashlib.sha256(files[0].read_bytes()).hexdigest())
        release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        uploads = [call for call in self.calls if call[:3] == ['gh', 'release', 'upload']]
        self.assertEqual(len(uploads), 1)
        self.assertNotIn('--clobber', uploads[0])
        self.assertEqual(uploads[0][-4:], list(map(str, files)))

    def test_a_production_attach_becomes_the_next_baseline_and_spends_its_growth_note(self):
        baseline = self.root / 'launcher/macos/bundle-size.json'
        image = len(b'fixture disk image')
        baseline.write_text(json.dumps({'format': 1, 'previous_release_dmg_bytes': image - 3,
                                        'growth_note': 'The runtime adds a required package.'}))
        self.prepare()
        release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        recorded = json.loads(baseline.read_text())
        self.assertEqual(recorded, {'format': 1, 'previous_release_dmg_bytes': image, 'growth_note': None})
        with self.assertRaises(ValueError):
            bundle.check_size(image * 2, recorded['previous_release_dmg_bytes'], recorded['growth_note'])

    def test_a_before_you_update_notice_is_signed_as_format_3_and_only_one_paragraph_packages(self):
        self.prepare()
        plain = json.loads(release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)[2].read_text())
        self.assertEqual(plain['format'], 2)
        self.assertNotIn('before_you_update', plain)
        shutil.rmtree(self.destination)

        notice = 'This version moves your radar to a new storage format. A backup is made first.'
        release.prepare(self.app, self.destination, 'v0.1.0', self.root, signing_key=self.signing_key,
                        passphrase=PASSPHRASE, notice=notice)
        files = release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)
        signed = json.loads(files[2].read_text())
        self.assertEqual((signed['format'], signed['before_you_update']), (3, notice))

        # A changed notice, or a notice in the wrong format, never attaches even when signed with the real key.
        private = serialization.load_pem_private_key(self.signing_key.read_bytes(), PASSPHRASE)
        original = files[2].read_bytes()
        for label, change, resign in [('edited', {'before_you_update': 'Download the fix from elsewhere.'}, False),
                                      ('format 2 with a notice', {'format': 2}, True),
                                      ('format 3 without one', {'before_you_update': None}, True)]:
            with self.subTest(label):
                metadata = {**signed, **change}
                if metadata['before_you_update'] is None:
                    metadata.pop('before_you_update')
                files[2].write_text(json.dumps(metadata, indent=2) + '\n')
                if resign:
                    files[3].write_bytes(private.sign(files[1].read_bytes() + files[2].read_bytes()))
                with self.assertRaises(ValueError):
                    release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)
        files[2].write_bytes(original)
        files[3].write_bytes(private.sign(files[1].read_bytes() + original))
        release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)
        shutil.rmtree(self.destination)

        for bad in ['', ' Padded.', 'Two\nlines.', 'A\ttab.', 'A line\u2028separator.', 'x' * 401]:
            with self.subTest(notice=bad), self.assertRaises(ValueError):
                release.prepare(self.app, self.destination, 'v0.1.0', self.root, signing_key=self.signing_key,
                                passphrase=PASSPHRASE, notice=bad)
            self.assertFalse(self.destination.exists())
        release.prepare(self.app, self.destination, 'v0.1.0', self.root, signing_key=self.signing_key,
                        passphrase=PASSPHRASE, notice='é' * 400)
        self.assertEqual(json.loads(release.verify(self.destination, 'v0.1.0', COMMIT, self.public_key)[2].read_text())
                         ['before_you_update'], 'é' * 400)

    def test_a_growth_note_installed_apps_cannot_read_never_packages(self):
        baseline = self.root / 'launcher/macos/bundle-size.json'
        for note in [{'text': 'The runtime adds a package.'}, ['The runtime adds a package.'], 7]:
            with self.subTest(note=note):
                baseline.write_text(json.dumps({'format': 1, 'previous_release_dmg_bytes': None, 'growth_note': note}))
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.destination.exists())
                self.assertEqual(list(self.destination.parent.glob('roleband-*')), [])

    def test_dirty_source_mismatched_tag_preview_and_wrong_architecture_never_package(self):
        for mode in ['dirty', 'tag', 'preview', 'demo', 'architecture', 'stale-build', 'dirty-build', 'no-spare', 'other-spare']:
            with self.subTest(mode=mode):
                self.dirty = mode == 'dirty'
                self.architecture = 'x86_64' if mode == 'architecture' else 'arm64'
                info_path = self.app / 'Contents/Info.plist'
                info = plistlib.loads(info_path.read_bytes())
                info.pop('RoleBandRegistration', None)
                info.pop('RoleBandDemoReleaseFile', None)
                info['RoleBandSourceRevision'] = 'b' * 40 if mode == 'stale-build' else COMMIT
                info['RoleBandSourceDirty'] = mode == 'dirty-build'
                info['RoleBandUpdateSpareKey'] = {'no-spare': None, 'other-spare': base64.b64encode(b'x' * 32).decode()}.get(mode, self.spare)
                if info['RoleBandUpdateSpareKey'] is None:
                    del info['RoleBandUpdateSpareKey']
                if mode == 'preview':
                    info['RoleBandRegistration'] = '/temporary/installation.json'
                if mode == 'demo':
                    info['RoleBandDemoReleaseFile'] = '/temporary/release.json'
                info_path.write_bytes(plistlib.dumps(info))
                with self.assertRaises(ValueError):
                    release.prepare(self.app, self.destination, 'v0.2.0' if mode == 'tag' else 'v0.1.0', self.root,
                                    signing_key=self.signing_key, passphrase=PASSPHRASE)
                self.assertFalse(self.destination.exists())
        self.assertFalse(any(call[0].endswith('make-dmg.sh') for call in self.calls))

    def test_corrupt_images_wrong_commits_and_extra_files_prevent_all_github_calls(self):
        self.prepare()
        image, *_ = release.names('0.1.0')
        original = (self.destination / image).read_bytes()
        self.calls.clear()
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', 'b' * 40, 'roleband/roleband', self.public_key, self.root)
        (self.destination / image).write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        (self.destination / image).write_bytes(original)
        (self.destination / 'unexpected.txt').write_text('not a release asset')
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertFalse(any(call[0] == 'gh' for call in self.calls))

    def test_moved_tags_and_draft_releases_never_upload(self):
        self.prepare()
        self.remote_commit = 'b' * 40
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.remote_commit = COMMIT
        self.draft = True
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertFalse(any(call[:3] == ['gh', 'release', 'upload'] for call in self.calls))

    def test_an_app_with_a_file_others_may_write_or_a_setuid_file_never_packages(self):
        tool = self.app / 'Contents/MacOS/RoleBandLauncher'
        tool.write_text('executable')
        for mode in (0o666, 0o4755, 0o2755, 0o775):
            with self.subTest(mode=oct(mode)):
                tool.chmod(mode)
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.destination.exists())
        tool.chmod(0o755)
        self.prepare()
        self.assertEqual(sum(call[0].endswith('make-dmg.sh') for call in self.calls), 1)

    def test_a_recorded_wider_signing_rule_is_the_one_a_release_must_carry(self):
        identity = self.root / 'launcher/macos/release-identity.json'
        pin = json.loads(identity.read_text())
        signer = plistlib.loads((self.app / 'Contents/Info.plist').read_bytes())['RoleBandSigningIdentity']
        wider = f'certificate leaf = H"{signer}" or (anchor apple generic and certificate leaf[subject.OU] = "ABCDE12345")'
        identity.write_text(json.dumps({**pin, 'update_requirement': wider}))
        with self.assertRaises(ValueError):
            self.prepare()
        path = self.app / 'Contents/Info.plist'
        path.write_bytes(plistlib.dumps({**plistlib.loads(path.read_bytes()), 'RoleBandUpdateRequirement': wider}))
        self.prepare()
        self.assertIn(['codesign', '--verify', '-R', '=' + wider, str(self.app)], self.calls)
        for bad in ['', ' ', 'x' * 1025]:
            identity.write_text(json.dumps({**pin, 'update_requirement': bad}))
            with self.subTest(rule=bad[:5]), self.assertRaises(ValueError):
                release.signing_rule(self.root, 'roleband/roleband', signer)

    def test_packaging_failure_leaves_no_partial_output(self):
        with patch.object(release.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, 'fixture')):
            with self.assertRaises(subprocess.CalledProcessError):
                self.prepare()
        self.assertFalse(self.destination.exists())

    def test_unsafe_and_invalid_asset_names_are_rejected(self):
        for value in ['0.1', '../0.1.0', '01.0.0', '0.1.0-rc.01', '0.1.0\n']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                release.names(value)

    def test_published_prereleases_upload_and_tampered_signatures_or_untrusted_keys_never_reach_github(self):
        self.prepare()
        self.prerelease = True
        release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertTrue(any(call[:3] == ['gh', 'release', 'upload'] for call in self.calls))
        self.calls.clear()
        other = self.root / 'other'
        signing.generate(other, 'Another trial')
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', other / 'release-public.pem', self.root)
        signature = self.destination / release.names('0.1.0')[3]
        signature.write_bytes(b'broken signature')
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertFalse(any(call[0] == 'gh' for call in self.calls))

    def test_only_the_recorded_certificate_and_release_key_make_or_attach_a_release(self):
        identity = self.root / 'launcher/macos/release-identity.json'
        recorded = identity.read_text()
        other = self.root / 'other'
        protected(other, 'Another self-made identity')
        foreign = signing.load_certificate(other)
        pin = json.loads(recorded)
        for name, value in [('certificate', {**pin, 'certificate_sha256': foreign.fingerprint(hashes.SHA256()).hex()}),
                            ('unrecorded', {'certificate_sha256': None, 'release_public_key': None})]:
            with self.subTest(name):
                identity.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.destination.exists())
        self.assertFalse(any(call[0].endswith('make-dmg.sh') for call in self.calls))
        identity.write_text(recorded)
        self.prepare()
        signing.record(other, self.root, replace=True)
        with self.assertRaises(ValueError):
            release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        self.assertFalse(any(call[0] == 'gh' for call in self.calls))

    def stamp(self, feed, keys):
        path = self.app / 'Contents/Info.plist'
        info = plistlib.loads(path.read_bytes())
        public = serialization.load_pem_public_key((keys / 'release-public.pem').read_bytes())
        info['RoleBandUpdateFeed'] = feed
        info['RoleBandSigningIdentity'] = (keys / 'identity').read_text()
        info['RoleBandUpdatePublicKey'] = base64.b64encode(public.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        spare = serialization.load_pem_public_key((keys / 'release-spare-public.pem').read_bytes())
        info['RoleBandUpdateSpareKey'] = base64.b64encode(spare.public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
        info['RoleBandUpdateRequirement'] = f'certificate leaf = H"{info['RoleBandSigningIdentity']}"'
        path.write_bytes(plistlib.dumps(info))
        self.certificate = signing.load_certificate(keys)

    def test_a_release_attaches_only_to_the_one_update_feed(self):
        self.prepare()
        self.calls.clear()
        for repository in ['roleband/roleband-mac-update-trial', 'example/roleband', 'roleband/roleband-copy']:
            with self.subTest(repository), self.assertRaises(ValueError):
                release.attach(self.destination, 'v0.1.0', COMMIT, repository, self.public_key, self.root)
        self.assertFalse(any(call[0] == 'gh' for call in self.calls))
        release.attach(self.destination, 'v0.1.0', COMMIT, 'roleband/roleband', self.public_key, self.root)
        uploads = [call for call in self.calls if call[:3] == ['gh', 'release', 'upload']]
        self.assertEqual([call[call.index('--repo') + 1] for call in uploads], ['roleband/roleband'])

    def test_an_app_stamped_with_another_feed_or_none_never_packages(self):
        keys = self.root / 'keys'
        for name, feed in [('another roleband feed', 'roleband/roleband-mac-update-trial'),
                           ('unknown feed', 'example/roleband'), ('no feed', None)]:
            with self.subTest(name):
                self.stamp(feed or 'placeholder', keys)
                if feed is None:
                    path = self.app / 'Contents/Info.plist'
                    info = plistlib.loads(path.read_bytes())
                    info.pop('RoleBandUpdateFeed')
                    path.write_bytes(plistlib.dumps(info))
                with self.assertRaises(ValueError):
                    self.prepare()
                self.assertFalse(self.destination.exists())
        self.assertFalse(any(call[0].endswith('make-dmg.sh') for call in self.calls))
        self.stamp('roleband/roleband', keys)
        self.prepare()
        self.assertTrue(self.destination.exists())

    def test_no_release_identity_exists_for_any_other_feed(self):
        for feed in ['roleband/roleband-mac-update-trial', 'example/roleband']:
            with self.subTest(feed):
                for lookup in (release.identity_path, lambda feed, root: release.release_identity(root, feed),
                               lambda feed, root: release.release_spare_key(root, feed)):
                    with self.assertRaises(ValueError):
                        lookup(feed, self.root)
        self.assertEqual(release.identity_path('roleband/roleband', self.root),
                         self.root / 'launcher/macos/release-identity.json')

    def test_prerelease_names_preserve_the_full_version(self):
        self.assertEqual(release.names('1.2.3-rc.1')[0], 'RoleBand-1.2.3-rc.1-macOS-arm64.dmg')


if __name__ == '__main__':
    unittest.main()
