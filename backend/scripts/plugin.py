"""Install, approve, enable and run plugins from the command line.

    .venv/bin/python -m scripts.plugin install ../examples/plugin-template
    .venv/bin/python -m scripts.plugin approve plugin-template      # shows what it may do, asks
    .venv/bin/python -m scripts.plugin enable plugin-template
    .venv/bin/python -m scripts.plugin run plugin-template refresh  # this process is the host
    .venv/bin/python -m scripts.plugin list
    .venv/bin/python -m scripts.plugin disable plugin-template
    .venv/bin/python -m scripts.plugin pause plugin-template        # resume; schedule <id> weekly|default
    .venv/bin/python -m scripts.plugin remove plugin-template       # data stays, unread
    .venv/bin/python -m scripts.plugin remove-data plugin-template --confirm plugin-template

The commands are `tracker.plugins.cli`'s, which says what each one does; the
supervisor runs that module for a plugin run.
"""

from __future__ import annotations

import sys

from tracker.plugins.cli import main

if __name__ == "__main__":
    sys.exit(main(prog="scripts.plugin"))
