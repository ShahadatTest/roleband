import base64
import json
import plistlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtendedKeyUsageOID

try:
    import signing
except ImportError:
    signing = None


def leaf(keys):
    return signing.load_certificate(keys)


def codesign(certificate):
    def run(command, **kwargs):
        for argument in command:
            if argument.startswith('--extract-certificates='):
                Path(argument.split('=', 1)[1] + '0').write_bytes(certificate.public_bytes(serialization.Encoding.DER))
        return subprocess.CompletedProcess(command, 0)
    return run


PASSPHRASE, CERTIFICATE_PASSWORD = b'release passphrase', b'certificate password'


def protected(keys, name='RoleBand'):
    """A release identity as the maintainer makes it: the spare apart, every key behind a password."""
    signing.generate(keys, name, spare_directory=keys.with_name(keys.name + '-spare'),
                     passphrase=PASSPHRASE, certificate_password=CERTIFICATE_PASSWORD)


class SigningTests(unittest.TestCase):
    def test_local_sealing_copies_the_candidate_preserves_its_source_and_embeds_the_trusted_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = root / 'keys'
            protected(keys, 'Local trial')
            (root / 'launcher/macos').mkdir(parents=True)
            (root / 'launcher/macos/release-identity.json').write_text('{"certificate_sha256": null, "release_public_key": null}')
            signing.record(keys, root)
            candidate = root / 'candidate/RoleBand.app'
            (candidate / 'Contents/Resources/engine').mkdir(parents=True)
            engine = candidate / 'Contents/Resources/engine/packaged.py'
            engine.write_text('immutable engine')
            # Code signatures ignore modes, so sealing must not carry these into a release.
            engine.chmod(0o666)
            helper = candidate / 'Contents/Resources/engine/helper'
            helper.write_text('setuid tool')
            helper.chmod(0o4755)
            (candidate / 'Contents/Resources').chmod(0o777)
            info_path = candidate / 'Contents/Info.plist'
            info_path.write_bytes(plistlib.dumps({'RoleBandReleaseCandidate': True,
                'RoleBandPackagedEngine': True, 'RoleBandSourceRevision': 'a' * 40,
                'RoleBandSourceDirty': False, 'RoleBandVersion': '1.2.3'}))
            original = info_path.read_bytes()
            target = root / 'signed/RoleBand.app'
            with patch.object(signing.subprocess, 'run', side_effect=codesign(leaf(keys))) as command, \
                    patch('bundle.sign_tree') as seal:
                signing.seal(candidate, target, (keys / 'identity').read_text(), None, keys / 'release-public.pem', root)
            self.assertIn(['codesign', '--verify', '--deep', '--strict', str(candidate)], [c.args[0] for c in command.call_args_list])
            self.assertEqual(seal.call_count, 1)
            self.assertEqual(seal.call_args.args[1:], ((keys / 'identity').read_text(), None))
            self.assertEqual(info_path.read_bytes(), original)
            info = plistlib.loads((target / 'Contents/Info.plist').read_bytes())
            self.assertNotIn('RoleBandReleaseCandidate', info)
            self.assertEqual(info['RoleBandUpdateRequirement'], f'certificate leaf = H"{(keys / "identity").read_text()}"')
            for path, mode in [('Contents/Resources/engine/packaged.py', 0o644), ('Contents/Resources/engine/helper', 0o755),
                               ('Contents/Resources', 0o755)]:
                self.assertEqual((target / path).stat().st_mode & 0o7777, mode, path)
            self.assertEqual(info['RoleBandUpdateFeed'], 'roleband/roleband')
            self.assertEqual(info['RoleBandSourceRevision'], 'a' * 40)
            public = serialization.load_pem_public_key((keys / 'release-public.pem').read_bytes())
            self.assertEqual(info['RoleBandUpdatePublicKey'], base64.b64encode(public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())
            self.assertEqual((target / 'Contents/Resources/engine/packaged.py').read_bytes(), engine.read_bytes())
            with self.assertRaises(FileExistsError):
                signing.seal(candidate, target, (keys / 'identity').read_text(), None, keys / 'release-public.pem', root)
            info = plistlib.loads(original)
            info['RoleBandSourceDirty'] = True
            info_path.write_bytes(plistlib.dumps(info))
            with self.assertRaises(ValueError):
                signing.seal(candidate, root / 'bad.app', (keys / 'identity').read_text(), None, keys / 'release-public.pem', root)
            self.assertFalse((root / 'bad.app').exists())
            info_path.write_bytes(original)
            other = root / 'other'
            signing.generate(other, 'Another self-made identity')
            with self.assertRaises(ValueError):
                signing.seal(candidate, root / 'foreign.app', (other / 'identity').read_text(), None, other / 'release-public.pem', root)
            self.assertFalse((root / 'foreign.app').exists())

    def test_a_seal_stamps_the_one_update_feed_and_no_tool_offers_a_feed_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys = root / 'keys'
            protected(keys)
            (root / 'launcher/macos').mkdir(parents=True)
            (root / 'launcher/macos/release-identity.json').write_text('{"certificate_sha256": null, "release_public_key": null}')
            signing.record(keys, root)
            candidate = root / 'candidate/RoleBand.app'
            (candidate / 'Contents').mkdir(parents=True)
            (candidate / 'Contents/Info.plist').write_bytes(plistlib.dumps({'RoleBandReleaseCandidate': True,
                'RoleBandPackagedEngine': True, 'RoleBandSourceRevision': 'a' * 40,
                'RoleBandSourceDirty': False, 'RoleBandVersion': '1.2.3'}))
            arguments = (candidate, root / 'RoleBand.app', (keys / 'identity').read_text(), None, keys / 'release-public.pem', root)
            with patch.object(signing.subprocess, 'run', side_effect=codesign(leaf(keys))), patch('bundle.sign_tree'):
                with self.assertRaises(TypeError):
                    signing.seal(*arguments, feed='trial')
                with self.assertRaises(TypeError):
                    signing.record(keys, root, replace=True, feed='trial')
                self.assertFalse((root / 'RoleBand.app').exists())
                signing.seal(*arguments)
            info = plistlib.loads((root / 'RoleBand.app/Contents/Info.plist').read_bytes())
            recorded = json.loads((root / 'launcher/macos/release-identity.json').read_text())
            self.assertEqual(info['RoleBandUpdateFeed'], 'roleband/roleband')
            self.assertEqual(info['RoleBandUpdatePublicKey'], recorded['release_public_key'])
            self.assertEqual(info['RoleBandUpdateSpareKey'], recorded['spare_release_public_key'])
            # The command line takes no feed, and makes no identity without passphrases and a separate spare.
            script = Path(signing.__file__)
            for command in (['seal', str(candidate), str(root / 'trial.app'), '--identity', 'AB',
                             '--release-public-key', str(keys / 'release-public.pem'), '--feed', 'trial'],
                            ['record', str(keys), '--feed', 'trial'],
                            ['generate', str(root / 'unprotected'), '--name', 'RoleBand', '--unprotected']):
                with self.subTest(command[0]):
                    result = subprocess.run([sys.executable, str(script), *command], capture_output=True, text=True,
                                            stdin=subprocess.DEVNULL, check=False)
                    self.assertEqual(result.returncode, 2, result.stderr)
            self.assertFalse((root / 'trial.app').exists() or (root / 'unprotected').exists())

    def test_sealing_refuses_a_second_identity_even_with_the_recorded_update_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            keys, other = root / 'keys', root / 'other'
            protected(keys)
            signing.generate(other, 'RoleBand')
            (root / 'launcher/macos').mkdir(parents=True)
            (root / 'launcher/macos/release-identity.json').write_text('{"certificate_sha256": null, "release_public_key": null}')
            signing.record(keys, root)
            candidate = root / 'candidate/RoleBand.app'
            (candidate / 'Contents').mkdir(parents=True)
            (candidate / 'Contents/Info.plist').write_bytes(plistlib.dumps({'RoleBandReleaseCandidate': True,
                'RoleBandPackagedEngine': True, 'RoleBandSourceRevision': 'a' * 40,
                'RoleBandSourceDirty': False, 'RoleBandVersion': '1.2.3'}))
            signed = root / 'signed'
            for name, identity, certificate in [('another certificate', other, leaf(other)),
                                                ('the recorded identity, another certificate', keys, leaf(other))]:
                with self.subTest(name), patch.object(signing.subprocess, 'run', side_effect=codesign(certificate)), \
                        patch('bundle.sign_tree') as sign:
                    with self.assertRaisesRegex(ValueError, 'recorded release certificate'):
                        signing.seal(candidate, signed / 'RoleBand.app', (identity / 'identity').read_text(), None,
                                     keys / 'release-public.pem', root)
                    self.assertEqual(sign.call_count, 1)
                    self.assertEqual(list(signed.iterdir()), [])
            with patch.object(signing.subprocess, 'run', side_effect=codesign(leaf(keys))), patch('bundle.sign_tree'):
                signing.seal(candidate, signed / 'RoleBand.app', (keys / 'identity').read_text(), None,
                             keys / 'release-public.pem', root)
            self.assertEqual([path.name for path in signed.iterdir()], ['RoleBand.app'])

    def test_the_release_identity_is_recorded_once_from_public_parts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launcher/macos').mkdir(parents=True)
            identity = root / 'launcher/macos/release-identity.json'
            identity.write_text('{"certificate_sha256": null, "release_public_key": null}')
            keys, other = root / 'keys', root / 'other'
            protected(keys)
            protected(other, 'Another self-made identity')
            signing.record(keys, root)
            recorded = identity.read_text()
            certificate = signing.load_certificate(keys)
            def raw(name):
                key = serialization.load_pem_public_key((keys / name).read_bytes())
                return base64.b64encode(key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
            self.assertEqual(json.loads(recorded), {'format': 1,
                'certificate_sha256': certificate.fingerprint(hashes.SHA256()).hex(),
                'release_public_key': raw('release-public.pem'),
                'spare_release_public_key': raw('release-spare-public.pem')})
            for secret in (PASSPHRASE, CERTIFICATE_PASSWORD):
                self.assertNotIn(secret.decode(), recorded)
            self.assertNotIn('PRIVATE', recorded)
            with self.assertRaises(ValueError):
                signing.record(other, root)
            self.assertEqual(identity.read_text(), recorded)
            signing.record(other, root, replace=True)
            self.assertNotEqual(identity.read_text(), recorded)
            # A key change keeps the signing rule that installed apps already hold.
            rule = 'certificate leaf = H"AB" or (anchor apple generic and certificate leaf[subject.OU] = "ABCDE12345")'
            identity.write_text(json.dumps({**json.loads(identity.read_text()), 'update_requirement': rule}))
            signing.record(keys, root, replace=True)
            self.assertEqual(json.loads(identity.read_text())['update_requirement'], rule)
            self.assertEqual(json.loads(identity.read_text())['release_public_key'], raw('release-public.pem'))

    def test_a_production_identity_needs_its_own_spare_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launcher/macos').mkdir(parents=True)
            identity = root / 'launcher/macos/release-identity.json'
            identity.write_text('{"certificate_sha256": null, "release_public_key": null}')
            keys = root / 'keys'
            protected(keys)
            spare = (keys / 'release-spare-public.pem').read_bytes()
            (keys / 'release-spare-public.pem').unlink()
            with self.assertRaises(ValueError):
                signing.record(keys, root)
            (keys / 'release-spare-public.pem').write_bytes((keys / 'release-public.pem').read_bytes())
            with self.assertRaises(ValueError):
                signing.record(keys, root)
            self.assertIsNone(json.loads(identity.read_text())['release_public_key'])
            (keys / 'release-spare-public.pem').write_bytes(spare)
            signing.record(keys, root)
            self.assertEqual(json.loads(identity.read_text())['spare_release_public_key'], base64.b64encode(
                serialization.load_pem_public_key(spare).public_bytes(
                    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode())

    def test_a_copy_of_the_release_identity_folder_unlocks_nothing_and_unprotected_keys_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'launcher/macos').mkdir(parents=True)
            identity = root / 'launcher/macos/release-identity.json'
            identity.write_text('{"certificate_sha256": null, "release_public_key": null}')
            keys, spare = root / 'keys', root / 'keys-spare'
            protected(keys)
            self.assertEqual(sorted(path.name for path in spare.iterdir()), ['release-spare-private.pem', 'release-spare-public.pem'])
            self.assertFalse((keys / 'release-spare-private.pem').exists())
            for name in ('p12-password', 'keychain-password'):
                self.assertFalse((keys / name).exists())
            for path in (keys / 'release-private.pem', spare / 'release-spare-private.pem'):
                with self.assertRaises(TypeError):
                    serialization.load_pem_private_key(path.read_bytes(), None)
                serialization.load_pem_private_key(path.read_bytes(), PASSPHRASE)
            with self.assertRaises(ValueError):
                pkcs12.load_key_and_certificates((keys / 'signing.p12').read_bytes(), None)
            pkcs12.load_key_and_certificates((keys / 'signing.p12').read_bytes(), CERTIFICATE_PASSWORD)
            with self.assertRaises(ValueError):
                signing.generate(root / 'nested', 'RoleBand', spare_directory=root / 'nested/spare',
                                 passphrase=PASSPHRASE, certificate_password=CERTIFICATE_PASSWORD)
            # Each way a production identity could be left unprotected is refused at recording.
            # Each case differs from a protected identity in one way only.
            for name, options in [('unencrypted keys', {'passphrase': None}),
                                  ('password files beside', {'certificate_password': None}),
                                  ('spare beside', {'spare_directory': None})]:
                folder = root / name.replace(' ', '-')
                signing.generate(folder, 'RoleBand', **{'spare_directory': folder.with_name(folder.name + '-spare'),
                    'passphrase': PASSPHRASE, 'certificate_password': CERTIFICATE_PASSWORD, **options})
                with self.subTest(name), self.assertRaises(ValueError):
                    signing.record(folder, root)
            self.assertIsNone(json.loads(identity.read_text())['release_public_key'])
            signing.record(keys, root)

    def test_failed_key_import_removes_only_its_scratch_keychain_and_hides_command_arguments(self):
        self.assertIsNotNone(signing)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'keys'
            signing.generate(target, 'RoleBand CI Trial')
            keychain = Path(directory) / 'trial.keychain-db'
            calls = []
            def fail(command, **kwargs):
                calls.append(command)
                if command[1] == 'import':
                    raise subprocess.CalledProcessError(1, command)
            with patch.object(signing.subprocess, 'run', side_effect=fail):
                with self.assertRaises(RuntimeError) as error:
                    signing.import_keychain(target, keychain)
            self.assertEqual(calls[-1], ['security', 'delete-keychain', str(keychain)])
            self.assertNotIn((target / 'p12-password').read_text(), str(error.exception))

    def test_throwaway_keys_have_code_signing_identity_private_permissions_and_cannot_be_overwritten(self):
        self.assertIsNotNone(signing, 'the signing-material generator is missing')
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'keys'
            signing.generate(target, 'RoleBand CI Trial')
            key, certificate, _ = pkcs12.load_key_and_certificates(
                (target / 'signing.p12').read_bytes(), (target / 'p12-password').read_bytes())
            self.assertIsNotNone(key)
            self.assertEqual(certificate.subject, certificate.issuer)
            self.assertIn(ExtendedKeyUsageOID.CODE_SIGNING, certificate.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value)
            self.assertEqual(certificate.fingerprint(hashes.SHA1()).hex().upper(), (target / 'identity').read_text())
            private = serialization.load_pem_private_key((target / 'release-private.pem').read_bytes(), None)
            public = serialization.load_pem_public_key((target / 'release-public.pem').read_bytes())
            public.verify(private.sign(b'checksum'), b'checksum')
            self.assertEqual(target.stat().st_mode & 0o777, 0o700)
            spare = serialization.load_pem_private_key((target / 'release-spare-private.pem').read_bytes(), None)
            serialization.load_pem_public_key((target / 'release-spare-public.pem').read_bytes()).verify(
                spare.sign(b'checksum'), b'checksum')
            self.assertNotEqual(spare.private_bytes_raw(), private.private_bytes_raw())
            for name in ('signing.p12', 'p12-password', 'release-private.pem', 'release-spare-private.pem', 'keychain-password'):
                self.assertEqual((target / name).stat().st_mode & 0o777, 0o600)
            original = (target / 'signing.p12').read_bytes()
            with self.assertRaises(FileExistsError):
                signing.generate(target, 'another identity')
            self.assertEqual((target / 'signing.p12').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
