"""The plugin template is a working plugin, and its CI's rules hold.

`examples/plugin-template` is what every plugin repo starts from, so it must
pass its own suite against the SDK in this tree, and the static check its CI
runs must catch a plugin that reaches the network on its own. Each check has a
planted hit; the template's clean scan is the positive control.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from roleband_plugin_sdk.checks import main as checks_main
from roleband_plugin_sdk.checks import scan, scan_source

REPO = Path(__file__).resolve().parents[2]
SDK = REPO / "sdk" / "python"
TEMPLATE = REPO / "examples" / "plugin-template"


def test_the_template_passes_its_own_suite_against_this_sdk(tmp_path):
    """Run as its CI does, in a copy (so no cache lands in the tree), with
    only the SDK and the template's own source on the path."""
    work = tmp_path / "plugin"
    shutil.copytree(TEMPLATE, work, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    env = {**os.environ, "PYTHONPATH": str(SDK), "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "-p", "no:asyncio"],
        cwd=work, env=env, capture_output=True, text=True, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stdout[-2000:] + done.stderr[-2000:]
    assert " passed" in done.stdout and "failed" not in done.stdout


def test_the_template_installs_the_sdk_s_in_repo_dependency_from_the_checkout():
    """`roleband-robots` lives in this repository and on no package index. A
    template CI or README that left pip to find it would fail on the first run,
    or install whatever someone published under that name."""
    sdk = tomllib.loads((SDK / "pyproject.toml").read_text())["project"]["dependencies"]
    assert any(dep.startswith("roleband-robots") for dep in sdk), "no in-repo dependency left: drop this test"
    ci = (TEMPLATE / ".github" / "workflows" / "ci.yml").read_text()
    readme = (TEMPLATE / "README.md").read_text()
    assert "robots/python" in ci.split("sparse-checkout:", 1)[1].split("- uses:", 1)[0], "not checked out"
    install = next(line for line in ci.splitlines() if "pip install" in line)
    assert install.index("./roleband/robots/python") < install.index("./roleband/sdk/python")
    develop = readme.split("## Develop", 1)[1]
    assert develop.index("robots/python") < develop.index("sdk/python")


def test_the_template_source_reaches_the_network_only_through_the_host():
    assert [str(f) for f in scan(TEMPLATE / "src")] == []


@pytest.mark.parametrize(
    "source",
    [
        "import httpx",
        "import requests as r",
        "from socket import create_connection",
        "import urllib.request",
        "from urllib import request",
        "from http.client import HTTPSConnection",
        "import subprocess",
        "from os import system",
        "import importlib",
        "mod = __import__('socket')",
        "import asyncio",
        "def f():\n    import ssl\n",
        # Each one gets past a scan that matches only a network module's import:
        "import os\nos.system('curl https://x')",
        "import os\nos.popen('id')",
        "import _socket",
        "from pip._vendor import requests",
        "import pkgutil\npkgutil.resolve_name('socket:socket')",
        "import logging.handlers",
        "exec('import socket')",
        "import builtins\nbuiltins.__import__('socket')",
        "import pty",
    ],
)
def test_the_check_finds_a_plugin_that_opens_its_own_connection(source):
    assert scan_source(source, Path("plugin.py")), source


@pytest.mark.parametrize(
    "source",
    ["from urllib.parse import urljoin", "from http import HTTPStatus", "import json, re, datetime", "import os.path",
     "import os\nos.environ.get('HOME')", "import logging\nlogging.getLogger(__name__)", "pattern.compile_rule()"],
)
def test_the_check_leaves_harmless_standard_modules_alone(source):
    assert scan_source(source, Path("plugin.py")) == []


def test_the_check_command_fails_on_a_planted_import(tmp_path, capsys):
    pkg = tmp_path / "src" / "bad_plugin"
    shutil.copytree(TEMPLATE / "src" / "roleband_plugin_template", pkg)
    assert checks_main([str(tmp_path / "src")]) == 0
    (pkg / "fetch.py").write_text("import httpx\n")
    assert checks_main([str(tmp_path / "src")]) == 1
    assert "fetch.py:1: imports httpx" in capsys.readouterr().out
