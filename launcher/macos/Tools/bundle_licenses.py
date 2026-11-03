"""Collect the notices actually supplied by installed runtime distributions.

A distribution whose files carry no licence text gets a pinned notice instead (`--notice NAME
VERSION PATH`); one with neither fails the build, as does a pin that fills no gap or names
another version, so the app never ships a package without its licence and no pin outlives it.
"""

import argparse
import hashlib
import json
import re
from importlib import metadata
from pathlib import Path


def normalized(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def generate(resources, distributions=None, pinned=()):
    destination = resources / 'licenses'
    pins = {normalized(name): (version, Path(path)) for name, version, path in pinned}
    problems = []
    rows, files = [], []
    for distribution in sorted(metadata.distributions() if distributions is None else distributions,
                               key=lambda item: item.metadata['Name'].lower()):
        name = distribution.metadata['Name']
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', name):
            raise ValueError('Invalid distribution name in license metadata')
        notices = []
        for file in sorted(distribution.files or [], key=str):
            filename = Path(file).name.lower()
            if filename.endswith(('.py', '.pyc', '.so', '.dylib')) or not any(
                token in filename for token in ('license', 'licence', 'notice', 'copying', 'copyright')
            ):
                continue
            source = Path(distribution.locate_file(file))
            if not source.is_file():
                continue
            target = Path('python-packages') / name / f'{len(notices):03d}-{source.name}'
            notices.append((target, str(file), source.read_bytes()))
        pin = pins.pop(normalized(name), None)
        if pin and notices:
            problems.append(f'the pinned notice for {name} fills no gap: it ships its own licence text; remove it')
        elif pin and pin[0] != distribution.version:
            problems.append(f'the pinned notice for {name} is for {pin[0]}, but {distribution.version} is installed; re-pin it')
        elif pin:
            notices.append((Path('python-packages') / name / '000-LICENSE', 'pinned', pin[1].read_bytes()))
        elif not notices:
            problems.append(f'{name} {distribution.version} ships no licence text; pin its upstream notice')
        files += [(target, content) for target, _, content in notices]
        rows.append({'name': name, 'version': distribution.version,
                     'license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'),
                     'notices': [{'path': str(target), 'source': origin, 'sha256': hashlib.sha256(content).hexdigest()}
                                 for target, origin, content in notices]})
    problems += [f'the pinned notice for {name} fills no gap: it is not installed; remove it' for name in pins]
    if problems:
        raise ValueError('\n'.join(problems))
    destination.mkdir(parents=True, exist_ok=True)
    for target, content in files:
        (destination / target).parent.mkdir(parents=True, exist_ok=True)
        (destination / target).write_bytes(content)
    (destination / 'python-packages.json').write_text(json.dumps(rows, indent=2) + '\n')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('resources', type=Path)
    parser.add_argument('--notice', nargs=3, action='append', default=[], metavar=('NAME', 'VERSION', 'PATH'),
                        help='the licence text for a distribution that ships none')
    args = parser.parse_args()
    generate(args.resources, pinned=args.notice)
