"""Which tiers of the Mac workflow a change needs: the native tests, the full bundle, or neither.

The workflow is a pull-request gate, so it takes no `paths:` filter: a required check from
a filtered workflow waits forever on a change the filter skips. Its first job runs this
script instead, and a job that is not needed reports as skipped, which counts as passed.

The watched paths come from the workflow (`NATIVE_PATHS`, `BUNDLE_PATHS`), one GitHub glob
per line: `**` crosses `/`, `*` and `?` do not. `backend/tests/test_ci_workflow_triggers.py`
holds that each list covers every file its tier's steps read.

Anything this script cannot judge runs everything: a release, a manual or scheduled run, a
push with no previous commit, or a diff git cannot produce. The bundle never runs for a
pull request; it is the slow tier, and every release builds it.
"""

import os
import re
import subprocess
import sys

EVERYTHING = {'release', 'workflow_dispatch', 'schedule'}
NO_COMMIT = re.compile(r'0*')


def glob_regex(pattern):
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif pattern[i] == '*':
            out.append('[^/]*')
            i += 1
        elif pattern[i] == '?':
            out.append('[^/]')
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile(''.join(out))


def patterns(text):
    return [line.strip() for line in text.splitlines() if line.strip()]


def matches(path, globs):
    return any(glob_regex(glob).fullmatch(path) for glob in globs)


def decide(event, changed, native_paths, bundle_paths):
    """`changed` is the list of changed files, or None when they could not be read."""
    if event in EVERYTHING or changed is None:
        return {'native': True, 'bundle': True}
    bundle = event == 'push' and any(matches(path, native_paths + bundle_paths) for path in changed)
    native = bundle or any(matches(path, native_paths) for path in changed)
    return {'native': native, 'bundle': bundle}


def changed_files(event, base, head):
    if not base or NO_COMMIT.fullmatch(base) or not head:
        return None
    span = f'{base}...{head}' if event == 'pull_request' else f'{base}..{head}'
    result = subprocess.run(['git', 'diff', '--name-only', span], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip(), file=sys.stderr)
        return None
    return result.stdout.split()


def main():
    event = os.environ['EVENT']
    changed = changed_files(event, os.environ.get('BASE', ''), os.environ.get('HEAD', ''))
    tiers = decide(event, changed, patterns(os.environ['NATIVE_PATHS']), patterns(os.environ['BUNDLE_PATHS']))
    seen = 'unknown' if changed is None else f'{len(changed)} changed files'
    print(f'{event}, {seen}: native {tiers["native"]}, bundle {tiers["bundle"]}')
    with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
        for tier, needed in tiers.items():
            output.write(f'{tier}={str(needed).lower()}\n')


if __name__ == '__main__':
    main()
