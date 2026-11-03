"""The always-on runtime must not depend on Docker.

A structural gate, not a style check. The point of the embedded database is
that a user installs nothing, and that promise breaks the moment any script on
the unattended path shells out to `docker compose` — the failure would surface
at 03:00 on someone's laptop as a scrape that silently never ran.

`docker-compose.yml` itself stays: it is optional dev tooling, and the
header says so.
"""

from __future__ import annotations

import re
import stat
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEPLOY = ROOT / "deploy"

# Everything launchd runs, the operator entry points — and `setup.sh`, the
# fresh-clone path. A gate scoped only to deploy/ would miss a Docker
# dependency in the first command a new user runs.
RUNTIME_SCRIPTS = sorted(DEPLOY.glob("*.sh")) + [DEPLOY / "roleband", ROOT / "setup.sh"]


def test_every_runtime_script_exists():
    assert RUNTIME_SCRIPTS, f"no deploy scripts found under {DEPLOY}"
    for script in RUNTIME_SCRIPTS:
        assert script.is_file(), f"{script} is referenced by this gate but missing"


def test_fresh_clone_setup_needs_no_database_install():
    """`setup.sh` is the first thing a new user runs; it must not gate on Docker."""
    body = (ROOT / "setup.sh").read_text()
    assert "Docker Desktop" not in body
    assert "scripts.install_pg_contrib" in body
    assert "scripts.build_pg_contrib" not in body
    assert body.index("scripts.install_pg_contrib") < body.index(".venv/bin/alembic upgrade head")


def test_fresh_clone_setup_provisions_the_embedding_model_before_the_first_scrape():
    """The first scrape's embeddings pass is fatal without weights, by design
    (`tracker/semantic/provision.py`: the pipeline fails honestly, the API degrades
    to lexical). So a setup that skips provisioning hands the user a scrape that
    cannot finish: on a fresh clone `./setup.sh` would succeed and the scrape
    its own closing text prescribes would stop at that pass. A development
    checkout never shows it because its weights are already there.
    """
    body = (ROOT / "setup.sh").read_text()
    provision = body.find("tracker.semantic.provision")
    first_scrape = body.find("tracker.daily")
    assert provision != -1, "setup.sh never provisions the embedding model"
    assert provision < first_scrape, "the model must be provisioned before the scrape setup.sh prescribes"


@pytest.mark.parametrize("script", RUNTIME_SCRIPTS, ids=lambda p: p.name)
def test_no_docker_on_the_unattended_path(script: Path):
    body = script.read_text()
    offenders = [
        line.strip()
        for line in body.splitlines()
        if "docker" in line and not line.lstrip().startswith("#")
    ]
    assert not offenders, f"{script.name} still shells out to Docker: {offenders}"


@pytest.mark.parametrize("script", ["install.sh", "uninstall.sh"])
def test_scripts_name_only_the_one_item(script: str):
    """Install and uninstall act on `com.roleband` alone, never on a label they
    did not install."""
    labels = set(re.findall(r"com\.roleband(?:\.[a-z]+)*", (DEPLOY / script).read_text()))
    assert labels == {"com.roleband"}, f"{script} names {sorted(labels)}"


@pytest.mark.parametrize(("body", "named"), [
    ("LABEL=com.roleband", {"com.roleband"}),
    ("unload com.roleband.api", {"com.roleband.api"}),
])
def test_the_label_scan_sees_another_label(body: str, named: set[str]):
    """The negative control for the check above."""
    assert set(re.findall(r"com\.roleband(?:\.[a-z]+)*", body)) == named


def test_one_agent_template_and_it_runs_the_named_launcher():
    """macOS names a background item after its program's file: `roleband`."""
    assert [p.name for p in DEPLOY.glob("*.plist.template")] == ["com.roleband.plist.template"]
    body = (DEPLOY / "com.roleband.plist.template").read_text()
    assert "<string>__ROLEBAND_ROOT__/deploy/roleband</string>" in body
    assert "/bin/bash" not in body


def test_uninstall_stops_the_embedded_server():
    """Nothing else will: the server outlives the processes that use it."""
    body = (DEPLOY / "uninstall.sh").read_text()
    assert "stop_server" in body


@pytest.mark.parametrize("script", RUNTIME_SCRIPTS, ids=lambda p: p.name)
def test_scripts_stay_executable(script: Path):
    assert script.stat().st_mode & stat.S_IXUSR, f"{script.name} lost its +x bit"


def _published_ports(compose: dict) -> list[str]:
    return [str(port) for service in compose["services"].values() for port in service.get("ports", [])]


@pytest.mark.parametrize(("mapping", "loopback"), [
    ("127.0.0.1:${POSTGRES_PORT:-5433}:5432", True),
    ("${POSTGRES_PORT:-5433}:5432", False),
    ("0.0.0.0:5433:5432", False),
    ("5432", False),
])
def test_the_loopback_rule_tells_a_local_mapping_from_an_open_one(mapping, loopback):
    """The negative controls for the check below: a mapping with no host
    address listens on every interface."""
    assert _is_loopback(mapping) is loopback


def _is_loopback(mapping: str) -> bool:
    return mapping.startswith(("127.0.0.1:", "[::1]:"))


def test_the_dev_database_listens_on_loopback_only():
    """Its credentials are a default anyone can read in this file, so a port
    open to the network is an open database."""
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    ports = _published_ports(compose)
    assert ports, "the dev database publishes a port; this check must see it"
    assert [p for p in ports if not _is_loopback(p)] == []
