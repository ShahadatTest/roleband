"""The daily heartbeat: which build, on what kind of machine, set up how.

Every value is a catalogue value (`registry.CATALOGUE["daily_heartbeat"]`).
`platform.processor()` is never called (it runs `uname -p`); the machine name,
user name, hostname and git branch are never read.
"""

from __future__ import annotations

import os
import platform
import sys
from collections.abc import Mapping
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import tracker
from tracker.config import get_settings
from tracker.db.models import TrackedCompany
from tracker.platform.os_region import read_os_region
from tracker.settings_store import (
    get_ai_egress_enabled,
    get_locale,
    get_persona_profile,
    get_role_answers,
)
from tracker.taxonomy.role_answers import RoleAnswer
from tracker.usage_stats.registry import CATALOGUE, COUNTRY, CRAFT, SENIORITY, followed_bucket

#: Set by a package or container build to say how this copy was installed.
INSTALL_METHOD_ENV = "ROLEBAND_INSTALL_METHOD"
_REPO_ROOT = Path(tracker.__file__).resolve().parents[2]

_OS = {"Darwin": "macos", "Linux": "linux", "Windows": "windows"}
_ARCH = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "AMD64": "x86_64", "amd64": "x86_64"}


def _major(release: str) -> int | None:
    head = release.split(".", 1)[0]
    return int(head) if head.isdigit() and int(head) < 1000 else None


def install_method(*, environ: Mapping[str, str], repo_root: Path, dockerenv: Path = Path("/.dockerenv")) -> str:
    declared = environ.get(INSTALL_METHOD_ENV, "").strip().lower()
    if declared in ("package", "container", "source"):
        return declared
    if dockerenv.exists():
        return "container"
    if (repo_root / ".git").exists():
        return "source"
    return "package"


def machine_facts(
    *,
    system: str,
    release: str,
    mac_release: str,
    machine: str,
    python_version: tuple[int, int],
    environ: Mapping[str, str],
    home: Path,
    repo_root: Path = _REPO_ROOT,
) -> dict[str, object]:
    """What the heartbeat says about this machine; no session needed."""
    facts: dict[str, object] = {
        "app_version": tracker.__version__,
        "os": _OS.get(system, "other"),
        "arch": _ARCH.get(machine, "other"),
        "python": f"{python_version[0]}.{python_version[1]}",
        "install_method": install_method(environ=environ, repo_root=repo_root),
    }
    major = _major(mac_release if system == "Darwin" and mac_release else release)
    if major is not None:
        facts["os_major"] = major
    country = read_os_region(system=system, home=home, environ=environ)
    if COUNTRY.accepts(country):
        facts["country"] = country
    return facts


def this_machine() -> dict[str, object]:
    return machine_facts(
        system=platform.system(),
        release=platform.release(),
        mac_release=platform.mac_ver()[0],
        machine=platform.machine(),
        python_version=(sys.version_info.major, sys.version_info.minor),
        environ=os.environ,
        home=Path.home(),
    )


def target_craft(answers: tuple[RoleAnswer, ...]) -> str | None:
    """The kind of role the answers look for, as a taxonomy slug: the one
    family they name, `several`, `any` when an answer takes every role of its
    kind, None with no answers. Never the user's own words."""
    if not answers:
        return None
    if any(answer.families is None for answer in answers):
        return "any"
    families = set().union(*(answer.families or () for answer in answers))
    return next(iter(families)) if len(families) == 1 else "several"


async def heartbeat(session: AsyncSession, machine: Mapping[str, object] | None = None) -> dict[str, object]:
    """The full heartbeat: the machine's facts plus how RoleBand is set up."""
    facts = dict(this_machine() if machine is None else machine)
    followed = (
        await session.execute(select(func.count()).select_from(TrackedCompany).where(TrackedCompany.enabled.is_(True)))
    ).scalar_one()
    facts["followed_bucket"] = followed_bucket(int(followed))
    facts["ai_egress"] = await get_ai_egress_enabled(session)
    facts["db_mode"] = "external" if get_settings().database_url_override else "embedded"
    language = (await get_locale(session)).get("language")
    ui_locale = CATALOGUE["daily_heartbeat"].props["ui_locale"]
    if ui_locale.accepts(language):
        facts["ui_locale"] = language
    craft = target_craft(await get_role_answers(session))
    if CRAFT.accepts(craft):
        facts["target_craft"] = craft
    seniority = (await get_persona_profile(session) or {}).get("target_stage")
    if SENIORITY.accepts(seniority):
        facts["target_seniority"] = seniority
    return facts
