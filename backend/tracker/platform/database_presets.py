"""The embedded database's memory presets, picked from the computer's memory.

Postgres's stock sizes suit a small shared server. A person's computer gives the
database more memory and an SSD, and a scan sorts and rewrites far more than the
stock sizes hold. A preset is passed on the server's command line at each start
(`embedded_db.ensure_server`), so nothing is written into the cluster's files and
a start without one returns the stock values.

Each preset also names itself and the memory it was picked from as `roleband.*`
settings, so the running server reports which preset it started with:
`SHOW roleband.preset`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal

from tracker.platform.memory import SMALL_BELOW

PresetName = Literal["small", "standard", "large"]

#: From this much installed memory a computer takes the Large preset.
LARGE_FROM = 32 * 2**30

#: Every preset: disk reads cost little more than cached ones on an SSD.
_PLANNER = {"random_page_cost": "1.1"}


@dataclass(frozen=True)
class DatabasePreset:
    """`shared_buffers` is held while the server runs; `work_mem` per sort and
    `maintenance_work_mem` per vacuum or index build only while those run.
    `effective_cache_size` takes no memory: it tells the planner how much the
    computer caches by itself."""

    name: PresetName
    settings: MappingProxyType[str, str] = field(repr=False)

    def server_settings(self, memory_bytes: int | None) -> dict[str, str]:
        """What the server starts with: the sizes, and what picked them."""
        return {
            **self.settings,
            "roleband.preset": self.name,
            "roleband.memory_bytes": "unknown" if memory_bytes is None else str(memory_bytes),
        }


def _preset(name: PresetName, **sizes: str) -> DatabasePreset:
    return DatabasePreset(name, MappingProxyType({**sizes, **_PLANNER}))


SMALL = _preset(
    "small", shared_buffers="256MB", work_mem="8MB", maintenance_work_mem="128MB",
    effective_cache_size="4GB",
)
STANDARD = _preset(
    "standard", shared_buffers="512MB", work_mem="16MB", maintenance_work_mem="256MB",
    effective_cache_size="8GB",
)
LARGE = _preset(
    "large", shared_buffers="1GB", work_mem="32MB", maintenance_work_mem="512MB",
    effective_cache_size="16GB",
)

PRESETS: MappingProxyType[str, DatabasePreset] = MappingProxyType(
    {preset.name: preset for preset in (SMALL, STANDARD, LARGE)}
)


def preset_for(memory_bytes: int | None) -> DatabasePreset:
    """Unknown memory is a small computer, as it is for the embedding model."""
    if memory_bytes is None or memory_bytes < SMALL_BELOW:
        return SMALL
    if memory_bytes < LARGE_FROM:
        return STANDARD
    return LARGE
