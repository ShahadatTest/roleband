"""How a plugin process starts: one command, for the host and for `FakeHost`.

The runner's interpreter is isolated (`-I`: no current directory, user
site-packages or PYTHON* variables on its path), which also ignores
PYTHONPATH, so its import path is the command's first argument: the SDK, then
the plugin's code, ahead of the venv's site-packages. It starts in `RUN_CWD`,
a directory no plugin can write, and inherits only `PASSED_ENV`. A plugin's
data directory comes in the `start` message, never as its working directory
nor on its path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

#: Environment a plugin process inherits; nothing else of the host's reaches it.
PASSED_ENV = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR")
#: Where the runner starts.
RUN_CWD = os.path.abspath(os.sep)
#: The runner's first code: the path argument goes first on `sys.path`, then
#: the runner runs as `__main__`.
BOOTSTRAP = (
    "import os, runpy, sys\n"
    "sys.path[0:0] = [p for p in sys.argv.pop(1).split(os.pathsep) if p]\n"
    "runpy.run_module('roleband_plugin_sdk.runner', run_name='__main__', alter_sys=True)\n"
)


def code_root(tree: Path) -> Path:
    """Where a plugin tree's importable code is: `src/` when it has one."""
    return tree / "src" if (tree / "src").is_dir() else tree


def runner_command(python: str, paths: Sequence[str | Path], entry: str, job: str) -> list[str]:
    """The runner's command line: isolated (`-I`), writing no bytecode (`-B`),
    importing from `paths` first, in order."""
    return [python, "-I", "-B", "-c", BOOTSTRAP, os.pathsep.join(str(p) for p in paths),
            "--entry", entry, "--job", job]


def runner_env(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    """The runner's environment: `PASSED_ENV`, as `environ` has them."""
    return {k: environ[k] for k in PASSED_ENV if k in environ}
