"""RoleBand plugin SDK: what a plugin imports, and nothing from the core.

A plugin is a `Plugin` with jobs. Each job gets a `JobContext` whose methods
are calls to the host: fetch through it, publish typed rows into the slots
the manifest declares, keep small state. See `examples/plugin-template`.

A preview: the manifest, this SDK and the host protocol may change between
releases.
"""

from .context import Company, HostError, JobContext, Pass, Refused, Response, RunEnded
from .manifest import ManifestError, PluginManifest, load_manifest, parse_manifest
from .plugin import Plugin
from .slots import (
    COMPANY_BENEFITS,
    COMPANY_FACTS,
    PAY_LEVELS,
    PAY_OBSERVATIONS,
    Benefit,
    FactClaim,
    PayLevel,
    PayObservation,
)
from .version import PROTOCOL_VERSION, SDK_RELEASES, SDK_VERSION

__version__ = SDK_VERSION

__all__ = [
    "COMPANY_BENEFITS",
    "COMPANY_FACTS",
    "PAY_LEVELS",
    "PAY_OBSERVATIONS",
    "PROTOCOL_VERSION",
    "SDK_RELEASES",
    "SDK_VERSION",
    "Benefit",
    "Company",
    "FactClaim",
    "HostError",
    "JobContext",
    "ManifestError",
    "PayLevel",
    "Pass",
    "PayObservation",
    "Plugin",
    "PluginManifest",
    "Refused",
    "Response",
    "RunEnded",
    "load_manifest",
    "parse_manifest",
]
