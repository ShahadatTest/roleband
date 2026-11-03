import argparse
import base64
import getpass
import hashlib
import json
import plistlib
import re
import stat
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from bundle import check_minimum_macos, check_size
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from repo_paths import ROOT

from tracker.platform.releases import validate_version

COMMIT = re.compile(r"[0-9a-f]{40}")
IDENTITY = Path('launcher/macos/release-identity.json')
# Where an app looks for updates is fixed when it is sealed, and this repository is the one feed.
FEED = 'roleband/roleband'
NOTICE_LIMIT = 400


def output(command, **kwargs):
    return subprocess.check_output(command, text=True, **kwargs).strip()


def names(version):
    validate_version(version)
    prefix = f"RoleBand-{version}-macOS-arm64"
    return prefix + ".dmg", prefix + ".sha256", prefix + ".json", prefix + ".sig"


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            checksum.update(block)
    return checksum.hexdigest()


def raw_key(path):
    if isinstance(path, bytes):
        if len(path) != 32:
            raise ValueError('Invalid Ed25519 public key size')
        return path
    key = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(key, ed25519.Ed25519PublicKey):
        raise ValueError('The release key must use Ed25519')
    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def identity_path(feed, root=ROOT):
    if feed != FEED:
        raise ValueError('Unknown update feed')
    return root / IDENTITY


def read_identity(path):
    pin = json.loads(path.read_text())
    certificate, key = pin.get('certificate_sha256'), pin.get('release_public_key')
    if not (isinstance(certificate, str) and re.fullmatch(r'[0-9a-f]{64}', certificate) and isinstance(key, str)):
        return None
    return certificate, raw_key(base64.b64decode(key, validate=True))


def release_identity(root=ROOT, feed=FEED):
    # Every release on the feed must carry the same certificate and update key: macOS ties
    # approvals to the certificate, and installed apps trust only their key.
    path = identity_path(feed, root)
    pinned = read_identity(path) if path.exists() else None
    if pinned is None:
        raise ValueError('Record the release certificate and key with Tools/signing.py record first')
    return pinned


def release_spare_key(root=ROOT, feed=FEED):
    """The spare release key recorded for the feed, or None for an identity recorded without one."""
    release_identity(root, feed)
    encoded = json.loads(identity_path(feed, root).read_text()).get('spare_release_public_key')
    if encoded is None:
        return None
    spare = raw_key(base64.b64decode(encoded, validate=True))
    if spare == release_identity(root, feed)[1]:
        raise ValueError('The spare release key must differ from the current one')
    return spare


def signing_rule(root, feed, identity):
    """The code requirement installed apps hold their updates to.

    By default an update must carry this release's certificate. The identity can record a wider
    rule, such as the certificate or an Apple Developer ID team, for the release that changes signer.
    """
    recorded = json.loads(identity_path(feed, root).read_text()).get('update_requirement')
    if recorded is not None:
        if not isinstance(recorded, str) or not recorded.strip() or len(recorded.encode()) > 1024:
            raise ValueError('The recorded update requirement must be one line of at most 1024 bytes')
        return recorded
    if not re.fullmatch(r'[0-9A-F]{40}', identity or ''):
        raise ValueError('Expected the signing identity as an upper-case SHA-1 fingerprint')
    return f'certificate leaf = H"{identity}"'


def check_modes(app):
    # Code signatures do not cover file modes, and installed apps refuse these.
    for path in [app, *app.rglob('*')]:
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            continue
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)) or mode & 0o6022:
            raise ValueError(f'Unsafe file mode in the app: {path.relative_to(app)}')


def check_signing_certificate(app, identity, trusted_certificate):
    with tempfile.TemporaryDirectory(prefix='roleband-certificate-') as directory:
        prefix = str(Path(directory) / 'cert')
        subprocess.run(['codesign', '--display', '--extract-certificates=' + prefix, str(app)], check=True, capture_output=True)
        certificate = x509.load_der_x509_certificate(Path(prefix + '0').read_bytes())
    if (certificate.subject != certificate.issuer
            or certificate.fingerprint(hashes.SHA1()).hex().upper() != identity
            or certificate.fingerprint(hashes.SHA256()).hex() != trusted_certificate):
        raise ValueError('The app is not signed with the recorded release certificate')
    certificate.verify_directly_issued_by(certificate)


def check_notice(notice):
    # Installed apps show the notice as one paragraph above Update and refuse a release whose notice
    # breaks these rules, so the tool refuses it first. Characters are counted as Unicode scalars.
    if notice is None:
        return
    if not (isinstance(notice, str) and notice and notice == notice.strip() and len(notice) <= NOTICE_LIMIT
            and not any(unicodedata.category(character) in ('Cc', 'Zl', 'Zp') for character in notice)):
        raise ValueError(f'A "Before you update" notice is one paragraph of at most {NOTICE_LIMIT} characters')


def manifest(version, commit, sha, size, public, previous, note, notice=None):
    # Format 3 is format 2 with a signed "Before you update" notice. A release without one stays format 2,
    # which apps that predate the notice still read.
    metadata = {"format": 2, "version": version, "commit": commit, "tag": "v" + version,
        "architecture": "arm64", "minimum_macos": "14.0", "signing": "self-signed", "notarized": False,
        "image": names(version)[0], "sha256": sha, "bytes": size,
        "release_key_sha256": hashlib.sha256(public).hexdigest(),
        "previous_release_dmg_bytes": previous, "growth_note": note}
    if notice is not None:
        metadata.update(format=3, before_you_update=notice)
    return metadata


def prepare(app, destination, tag=None, root=ROOT, *, signing_key=None, passphrase=None, notice=None):
    check_notice(notice)
    version = json.loads((root / "dashboard/package.json").read_text())["version"]
    image_name, checksum_name, manifest_name, signature_name = names(version)
    if signing_key is None:
        raise ValueError('A release signing key is required')
    try:
        private = serialization.load_pem_private_key(signing_key.read_bytes(), passphrase)
    except TypeError:
        raise ValueError('The release key and its passphrase do not go together') from None
    if not isinstance(private, ed25519.Ed25519PrivateKey):
        raise ValueError('The release key must use Ed25519')
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    feed = info.get("RoleBandUpdateFeed")
    if feed != FEED:
        raise ValueError("The app is not stamped with the update feed " + FEED)
    trusted_certificate, trusted_key = release_identity(root, feed)
    if public != trusted_key:
        raise ValueError('The signing key is not the recorded release key')
    if passphrase is None:
        raise ValueError('The production release key must be passphrase-protected')
    if tag is not None and tag != "v" + version:
        raise ValueError("The release tag does not match dashboard/package.json")
    if destination.exists():
        raise ValueError("The release output directory already exists")
    commit = output(["git", "rev-parse", "HEAD"], cwd=root)
    if not COMMIT.fullmatch(commit) or output(["git", "status", "--porcelain", "--untracked-files=normal"], cwd=root):
        raise ValueError("Release assets require a clean checkout at a commit")
    required = {"CFBundleIdentifier": "com.roleband.launcher", "CFBundleExecutable": "RoleBandLauncher",
                "CFBundleName": "RoleBand", "CFBundleDisplayName": "RoleBand", "LSUIElement": True,
                "RoleBandSourceRevision": commit, "RoleBandSourceDirty": False,
                "RoleBandVersion": version, "CFBundleShortVersionString": version.split('-')[0].split('+')[0],
                "CFBundleVersion": version.split('-')[0].split('+')[0], "RoleBandPackagedEngine": True,
                "RoleBandUpdatePublicKey": base64.b64encode(public).decode('ascii'), "LSMinimumSystemVersion": "14.0"}
    spare = release_spare_key(root, feed)
    required['RoleBandUpdateSpareKey'] = None if spare is None else base64.b64encode(spare).decode('ascii')
    required['RoleBandUpdateRequirement'] = signing_rule(root, feed, info.get('RoleBandSigningIdentity'))
    if (any(info.get(key) != value for key, value in required.items())
            or "RoleBandRegistration" in info or "RoleBandDemoReleaseFile" in info or info.get("RoleBandPreview")):
        raise ValueError("The app identity/version is not a distributable RoleBand launcher")
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    signature = subprocess.run(["codesign", "--display", "--verbose=4", str(app)], check=True, capture_output=True, text=True)
    if "Signature=adhoc" in signature.stderr.splitlines():
        raise ValueError("The release requires RoleBand's signing certificate")
    check_signing_certificate(app, info.get('RoleBandSigningIdentity'), trusted_certificate)
    check_modes(app)
    subprocess.run(['codesign', '--verify', '-R', '=' + required['RoleBandUpdateRequirement'], str(app)], check=True)
    if output(["lipo", "-archs", str(app / "Contents/MacOS/RoleBandLauncher")]) != "arm64":
        raise ValueError("The release executable must be Apple silicon only")
    build = output(["xcrun", "vtool", "-show-build", str(app / "Contents/MacOS/RoleBandLauncher")])
    if re.findall(r"^\s*minos\s+(\S+)\s*$", build, re.MULTILINE) != ["14.0"]:
        raise ValueError("The executable deployment target does not match macOS 14.0")
    check_minimum_macos(app)
    destination.parent.mkdir(parents=True, exist_ok=True)
    baseline = json.loads((root / 'launcher/macos/bundle-size.json').read_text())
    with tempfile.TemporaryDirectory(prefix="roleband-release-", dir=destination.parent) as directory:
        staging = Path(directory)
        image = staging / image_name
        subprocess.run([str(root / "launcher/macos/make-dmg.sh"), str(app), str(image)], check=True)
        sha = digest(image)
        size = image.stat().st_size
        check_size(size, baseline['previous_release_dmg_bytes'], baseline['growth_note'])
        (staging / checksum_name).write_text(f"{sha}  {image_name}\n")
        (staging / manifest_name).write_text(json.dumps(manifest(version, commit, sha, size, public,
            baseline['previous_release_dmg_bytes'], baseline['growth_note'], notice), indent=2) + "\n")
        (staging / signature_name).write_bytes(private.sign((staging / checksum_name).read_bytes() + (staging / manifest_name).read_bytes()))
        verify(staging, "v" + version, commit, public)
        staging.rename(destination)
    return destination


def candidate(app, destination, root=ROOT):
    version = json.loads((root / 'dashboard/package.json').read_text())['version']
    validate_version(version)
    commit = output(['git', 'rev-parse', 'HEAD'], cwd=root)
    if (destination.exists() or not COMMIT.fullmatch(commit)
            or output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=root)):
        raise ValueError('A candidate requires a clean checkout and a new destination')
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if (info.get('RoleBandReleaseCandidate') is not True or info.get('RoleBandPackagedEngine') is not True
            or info.get('RoleBandVersion') != version or info.get('RoleBandSourceRevision') != commit
            or info.get('RoleBandSourceDirty') is not False or 'RoleBandUpdatePublicKey' in info
            or any(key in info for key in ('RoleBandSigningIdentity', 'RoleBandUpdateFeed', 'RoleBandUpdateSpareKey',
                                           'RoleBandUpdateRequirement'))):
        raise ValueError('The app is not an unsigned release candidate from this source')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    baseline = json.loads((root / 'launcher/macos/bundle-size.json').read_text())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='roleband-candidate-', dir=destination.parent) as directory:
        staging = Path(directory)
        image = staging / f'RoleBand-{version}-macOS-arm64-candidate.dmg'
        subprocess.run([str(root / 'launcher/macos/make-dmg.sh'), str(app), str(image)], check=True)
        size = image.stat().st_size
        check_size(size, baseline['previous_release_dmg_bytes'], baseline['growth_note'])
        sha = digest(image)
        metadata = {'candidate_format': 1, 'release_ready': False, 'signing': 'ad-hoc',
            'version': version, 'commit': commit, 'image': image.name, 'sha256': sha, 'bytes': size,
            'installed_bytes': sum(path.stat().st_size for path in app.rglob('*') if path.is_file() and not path.is_symlink()),
            **baseline}
        (staging / 'candidate.json').write_text(json.dumps(metadata, indent=2) + '\n')
        (staging / 'candidate.sha256').write_text(f'{sha}  {image.name}\n')
        staging.rename(destination)
    return destination


def verify(directory, tag, commit, public_key):
    if not tag.startswith("v") or not COMMIT.fullmatch(commit):
        raise ValueError("Expected an exact release tag and commit")
    image_name, checksum_name, manifest_name, signature_name = names(tag[1:])
    expected = {image_name, checksum_name, manifest_name, signature_name}
    if {path.name for path in directory.iterdir()} != expected:
        raise ValueError("The artifact has missing or unexpected files")
    if any((directory / name).is_symlink() or not (directory / name).is_file() for name in expected):
        raise ValueError("Release artifacts must be regular files")
    if (directory / manifest_name).stat().st_size > 4096 or (directory / checksum_name).stat().st_size > 512:
        raise ValueError("Release metadata exceeds its size limit")
    metadata = json.loads((directory / manifest_name).read_text())
    if not isinstance(metadata, dict) or (directory / signature_name).stat().st_size != 64:
        raise ValueError('Invalid release metadata or signature size')
    sha = digest(directory / image_name)
    public = raw_key(public_key)
    expected_metadata = manifest(tag[1:], commit, sha, (directory / image_name).stat().st_size, public,
        metadata.get('previous_release_dmg_bytes'), metadata.get('growth_note'), metadata.get('before_you_update'))
    check_notice(metadata.get('before_you_update'))
    if metadata != expected_metadata or (directory / checksum_name).read_text() != f"{sha}  {image_name}\n":
        raise ValueError("The image, checksum, version or source commit does not match")
    check_size(metadata['bytes'], metadata['previous_release_dmg_bytes'], metadata['growth_note'])
    signature = (directory / signature_name).read_bytes()
    if len(signature) != 64:
        raise ValueError('Invalid release signature size')
    try:
        ed25519.Ed25519PublicKey.from_public_bytes(public).verify(signature,
            (directory / checksum_name).read_bytes() + (directory / manifest_name).read_bytes())
    except InvalidSignature:
        raise ValueError('The release signature does not match the trusted key') from None
    return [directory / name for name in (image_name, checksum_name, manifest_name, signature_name)]


def attach(directory, tag, commit, repository, public_key, root=ROOT):
    if repository != FEED:
        raise ValueError("Releases attach only to the update feed " + FEED)
    if raw_key(public_key) != release_identity(root, repository)[1]:
        raise ValueError('The public key is not the release key recorded for ' + repository)
    files = verify(directory, tag, commit, public_key)
    release = json.loads(output(["gh", "release", "view", tag, "--repo", repository, "--json", "tagName,isDraft,isPrerelease"]))
    if (release.get('tagName') != tag or release.get('isDraft') is not False
            or not isinstance(release.get('isPrerelease'), bool)):
        raise ValueError("Assets attach only to an existing published release")
    resolved = output(["gh", "api", f"repos/{repository}/commits/{tag}", "--jq", ".sha"])
    if resolved != commit:
        raise ValueError("The release tag moved or names a different source commit")
    # Without --clobber a rerun cannot replace an already published asset.
    subprocess.run(["gh", "release", "upload", tag, "--repo", repository, *map(str, files)], check=True)
    # The next release grows from this one, and a growth note excuses only the release it was written for.
    (root / 'launcher/macos/bundle-size.json').write_text(json.dumps({'format': 1,
        'previous_release_dmg_bytes': json.loads(files[2].read_text())['bytes'], 'growth_note': None}, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("prepare")
    build.add_argument("app", type=Path)
    build.add_argument("directory", type=Path)
    build.add_argument("--tag")
    build.add_argument('--signing-key', type=Path, required=True)
    build.add_argument('--before-you-update', dest='notice',
                       help='One paragraph shown above Update, signed with the release')
    unsigned = commands.add_parser('candidate')
    unsigned.add_argument('app', type=Path)
    unsigned.add_argument('directory', type=Path)
    publish = commands.add_parser("attach")
    publish.add_argument("directory", type=Path)
    publish.add_argument("--tag", required=True)
    publish.add_argument("--commit", required=True)
    publish.add_argument("--repository", required=True)
    publish.add_argument('--public-key', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            passphrase = None
            try:
                serialization.load_pem_private_key(args.signing_key.read_bytes(), None)
            except TypeError:
                passphrase = getpass.getpass('Release key passphrase: ').encode()
            print(prepare(args.app.resolve(), args.directory.absolute(), args.tag,
                          signing_key=args.signing_key, passphrase=passphrase, notice=args.notice))
        elif args.command == 'candidate':
            print(candidate(args.app.resolve(), args.directory.absolute()))
        else:
            attach(args.directory.resolve(), args.tag, args.commit, args.repository, args.public_key)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Release packaging failed: {error}\n")


if __name__ == "__main__":
    main()
