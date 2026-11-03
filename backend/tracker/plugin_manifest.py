"""Plugin manifests, as the core accepts them.

The SDK (`roleband_plugin_sdk.manifest`) validates a manifest on its own
terms: shape, slots, hosts, jobs. This module adds what only the core knows:

- the ids a plugin may not take, because a core source already answers to
  them (`company_fact.source`, the provider column) or the core reserves
  them (`builtin`);
- the SDK the core ships, which the manifest's `sdk` range must admit;
- the trust ceiling on a plugin's company-fact claims.

A manifest that claims a company fact other than headcount is refused by the
SDK itself, so no core rule repeats it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from roleband_plugin_sdk.manifest import PluginManifest

__all__ = [
    "COMPANY_FACTS",
    "CORE_SOURCES",
    "FACT_RANK_CEILING",
    "RESERVED_IDS",
    "accept",
    "fact_rank",
    "fact_rank_of",
    "load",
]

#: The SDK is imported only where a manifest is validated (install, the plugin
#: host process). The API, scheduler and pipeline read the manifest the core
#: stored at install, as JSON, and never load the SDK: this module's constants
#: and `fact_rank_of` work without it.
COMPANY_FACTS = "company.facts"

#: Ids the core owns. Every core claim source that fits the plugin-id pattern
#: is here (`tests/test_plugin_manifest.py` checks it against
#: `profiles.sources.SOURCES`), plus the names the plugin registry uses.
RESERVED_IDS = frozenset(
    {
        "atlas",
        "blueprint",
        "builtin",
        "core",
        "employer",
        "heuristic",
        "manual",
        "market",
        "estimated",
        "reported",
        "roleband",
        # `comp_snapshot.source` of pay-trend rows that hold our series and a
        # plugin's together: never a plugin's id.
        "mixed",
    }
)

#: Every provider value the core itself writes: the ids above plus the core
#: claim sources a plugin id could never spell. The registry reads a value
#: outside this set only for the plugin it belongs to;
#: `tests/test_plugin_manifest.py` checks it covers `profiles.sources.SOURCES`.
CORE_SOURCES = RESERVED_IDS | frozenset({"sec_edgar", "dol_lca"})

#: A plugin's fact claims rank at most this high, so a plugin never outranks
#: an official source: filings, the employer, the blueprint.
FACT_RANK_CEILING = 50
#: The rank a `company.facts` provider gets when its manifest names none.
DEFAULT_FACT_RANK = FACT_RANK_CEILING


def accept(manifest: PluginManifest) -> PluginManifest:
    """`manifest` if the core accepts it; otherwise `ManifestError` with every reason."""
    from roleband_plugin_sdk import SDK_VERSION
    from roleband_plugin_sdk.manifest import ManifestError, spec_admits

    problems = []
    plugin = manifest.plugin
    if plugin.id in RESERVED_IDS:
        problems.append(f"plugin.id: {plugin.id!r} is reserved by the core")
    if not spec_admits(plugin.sdk, SDK_VERSION):
        problems.append(f"plugin.sdk: {plugin.sdk!r} does not admit the SDK this core ships ({SDK_VERSION})")
    if problems:
        raise ManifestError(problems)
    return manifest


def load(path: str | Path) -> PluginManifest:
    """The manifest at `path` (a file or a plugin directory), validated by the
    SDK and accepted by the core."""
    from roleband_plugin_sdk.manifest import load_manifest

    return accept(load_manifest(path))


def fact_rank_of(provides: Iterable[Mapping[str, Any]]) -> int | None:
    """The capped fact rank from a manifest's `provides` entries, as stored
    (`PluginManifest.model_dump()["provides"]`); None without `company.facts`."""
    for entry in provides:
        if entry.get("slot") == COMPANY_FACTS:
            return min(entry.get("rank") or DEFAULT_FACT_RANK, FACT_RANK_CEILING)
    return None


def fact_rank(manifest: PluginManifest) -> int | None:
    """The trust rank the core gives this plugin's fact claims, capped; None
    when it provides no `company.facts`."""
    return fact_rank_of(p.model_dump() for p in manifest.provides)
