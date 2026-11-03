"""Isolated entry point for the engine shipped inside RoleBand.app."""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    # -I omits both the working directory and PYTHONPATH. Only this bundle's
    # engine is added; every child inherits the same packaged-mode selection.
    # Children start without -I, so the environment keeps the person's own
    # user site, and any .pth file in it, out of them.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.dont_write_bytecode = True
    os.environ["ROLEBAND_PACKAGED"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.environ["PYTHONNOUSERSITE"] = "1"
    from tracker import __version__

    args = sys.argv[1:]
    if args == ["--version"]:
        print(__version__)
        return
    if args == ["prepare-database"]:
        from tracker.supervisor.prepare import migrate

        migrate()
        return
    if not args or args[0] not in {"supervisor", "mcp.server", "probe"}:
        sys.exit("usage: packaged.py {supervisor|mcp.server|probe} [arguments]")
    if args[:2] == ["supervisor", "run"]:
        from tracker.supervisor.prepare import run

        run()
    module = 'tracker.supervisor.bundle_probe' if args[0] == 'probe' else f"tracker.{args[0]}"
    sys.argv = [module, *args[1:]]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
