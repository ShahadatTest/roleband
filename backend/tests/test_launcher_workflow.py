"""Hosted builds produce candidates without release credentials or write tokens."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/mac-launcher.yml"


def test_hosted_jobs_have_no_write_token_or_signing_secrets():
    text = WORKFLOW.read_text()
    data = yaml.safe_load(text)
    assert data["permissions"] == {"contents": "read"}
    assert all(job.get("permissions", data["permissions"]) == {"contents": "read"}
               for job in data["jobs"].values())
    assert 'secrets.' not in text
    assert 'security import' not in text
    assert 'signing.py' not in text


def test_ci_exports_a_candidate_instead_of_publishing_an_unapproved_release():
    data = yaml.safe_load(WORKFLOW.read_text())
    assert 'attach' not in data['jobs']
    steps = data['jobs']['bundle']['steps']
    commands = '\n'.join(step.get('run', '') for step in steps)
    assert 'release.py candidate' in commands
    assert 'release.py prepare' not in commands
    assert 'release.py attach' not in commands
    assert '--signing-key' not in commands
    artifacts = [step['with']['name'] for step in steps if step.get('uses', '').startswith('actions/upload-artifact@')]
    assert 'macos-candidate-arm64' in artifacts
    assert 'macos-release-arm64' not in artifacts
    assert 'prerelease' not in str(data['jobs']['build'].get('if', ''))


def test_the_candidate_is_probed_without_its_swift_build_folder_and_source_rendering_still_runs():
    data = yaml.safe_load(WORKFLOW.read_text())
    job = data['jobs']['bundle']
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert 'build-bundle.sh' in commands
    # Only the stamped build tells the bundle which dashboard tree it holds.
    assert commands.index('deploy/build_dashboard.sh') < commands.index('build-bundle.sh')
    assert 'npm run build' not in commands
    assert '--identity' not in commands and '--release-public-key' not in commands
    assert '--check-engine' in commands and '--check-copy' in commands
    assert 'mv "$RUNNER_TEMP/roleband-cache/swift"' in commands
    assert 'chmod -R a-w' in commands
    assert 'sudo' not in commands
    source_checks = '\n'.join(step.get('run', '') for step in data['jobs']['build']['steps'])
    assert '--render-panel' in source_checks and '--lang=es' in source_checks


def test_the_built_app_http_client_is_tested_against_the_binary_the_build_produced():
    steps = yaml.safe_load(WORKFLOW.read_text())['jobs']['build']['steps']
    commands = [step.get('run', '') for step in steps]
    build = next(i for i, command in enumerate(commands) if 'launcher/macos/build-app.sh' in command)
    moved = next(i for i, command in enumerate(commands) if 'mv launcher/macos/.build "$RUNNER_TEMP/launcher-build"' in command)
    transport = [i for i, command in enumerate(commands) if 'launcher/macos/test-transport.py' in command]
    assert transport, 'the transport test does not run'
    assert build < moved < transport[0]
    assert '"$RUNNER_TEMP/launcher-build/RoleBand Launcher.app/Contents/MacOS/RoleBandLauncher"' in commands[transport[0]]


def test_the_bundle_restores_its_verified_downloads_and_wheels_keyed_on_their_pins():
    steps = yaml.safe_load(WORKFLOW.read_text())['jobs']['bundle']['steps']
    caches = [(i, step['with']) for i, step in enumerate(steps) if step.get('uses', '').startswith('actions/cache@')]
    build = next(i for i, step in enumerate(steps) if 'build-bundle.sh' in step.get('run', ''))
    packaging = next(i for i, step in enumerate(steps) if 'packaging-requirements.txt' in step.get('run', ''))
    assert caches and all(i < min(build, packaging) for i, _ in caches)
    by_path = {config['path']: config['key'] for _, config in caches}
    command = steps[build]['run']
    cache_folder = command.split('--cache ', 1)[1].split()[0].strip('"').replace('$RUNNER_TEMP', '${{ runner.temp }}')
    downloads = [path for path in by_path if path.startswith(cache_folder + '/')]
    assert downloads, 'the folder bundle.py downloads into is not cached'
    assert "hashFiles('launcher/macos/runtime.json')" in by_path[downloads[0]]
    # The Swift build shares the cache folder and is moved aside before the job ends; only the
    # downloads belong in the cache.
    assert all(path != cache_folder for path in by_path)
    assert "launcher/macos/runtime-lock.txt" in by_path['~/Library/Caches/pip']
    assert all((ROOT / name).is_file() for key in by_path.values()
               for name in re.findall(r"'([^']+)'", key))


def test_the_backend_lint_covers_the_packaging_tools_and_the_transport_test():
    backend = yaml.safe_load((ROOT / '.github/workflows/backend.yml').read_text())['jobs']['checks']
    lint = next(step['run'].split() for step in backend['steps'] if step.get('run', '').startswith('ruff check'))
    assert backend['defaults']['run']['working-directory'] == 'backend'
    assert {'../launcher/macos/Tools', '../launcher/macos/test-transport.py'} <= set(lint)
    assert (ROOT / 'launcher/macos/test-transport.py').is_file()


#: Spellings Swift 6.2 introduced. The Xcode CI pins (16.4, Swift 6.1) rejects
#: each one, while a newer local compiler accepts it, so only CI would notice.
SWIFT_62_ONLY = (r"nonisolated\(nonsending\)", r"@concurrent\b")


def test_the_launcher_uses_no_swift_newer_than_the_ci_compiler():
    assert "Xcode_16.4.app" in WORKFLOW.read_text(), "CI's Xcode moved: revisit SWIFT_62_ONLY"
    sources = [path for folder in ("Sources", "Tests") for path in sorted((ROOT / "launcher/macos" / folder).rglob("*.swift"))]
    assert sources
    hits = [f"{path.relative_to(ROOT)}:{number}" for path in sources
            for number, line in enumerate(path.read_text().splitlines(), 1)
            if any(re.search(pattern, line) for pattern in SWIFT_62_ONLY)]
    assert hits == []
