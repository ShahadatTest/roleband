"""The repository the packaging tools build from, with its backend importable.

Every tool that imports `tracker` imports this module itself, so none relies on
another tool having set the path. Ruff's isort keeps the order: `tracker` is
first-party in the backend config and sorts after this module.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / 'backend'

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
