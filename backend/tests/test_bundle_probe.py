"""The headless bundle probe cannot attach an installed user's database."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize('bad', ['database', 'state', 'python'])
def test_probe_accepts_only_its_scratch_state_and_bundled_python(tmp_path, bad):
    from tracker.supervisor.bundle_probe import validate_paths

    resources = tmp_path / 'RoleBand.app/Contents/Resources'
    scratch = tmp_path / 'scratch'
    values = [scratch / 'db', scratch / 'home/.roleband', resources / 'python']
    validate_paths(scratch, resources, *values)
    values[{'database': 0, 'state': 1, 'python': 2}[bad]] = Path('/another/install')
    with pytest.raises(ValueError):
        validate_paths(scratch, resources, *values)


def test_explicit_scratch_server_stop_does_not_leave_a_broken_exit_callback(tmp_path):
    script = '''
from pathlib import Path
import sys
from tracker.platform.embedded_db import ensure_server, stop_server
pgdata = Path(sys.argv[1])
ensure_server(pgdata, database='probe')
assert stop_server(pgdata)
'''
    result = subprocess.run([sys.executable, '-B', '-c', script, str(tmp_path / 'db')],
        env={**os.environ, 'ROLEBAND_PGDATA': str(tmp_path / 'db'), 'ROLEBAND_DATABASE_URL': ''},
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'Exception ignored' not in result.stderr, result.stderr
