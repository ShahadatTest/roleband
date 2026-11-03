"""Connector API version + capability negotiation.

Two-part contract, deliberately:

- `CONNECTOR_API_VERSION` is an integer bumped only for a genuine break.
- `Capabilities` is negotiated at load, so *additive* transport ability
  (streaming, render, POST) never forces a major bump. A connector declares what
  it requires; the runtime declares what it can provide; the mismatch is a clear
  load-time error instead of a mid-scrape `AttributeError`.
"""

from __future__ import annotations

from dataclasses import dataclass, fields

__all__ = [
    "CONNECTOR_API_VERSION",
    "Capabilities",
    "CapabilityError",
    "negotiate",
]

#: Bump only on a breaking change to the SDK protocols in `sdk.types` /
#: `sdk.context`. Additive capability goes in `Capabilities`, not here.
CONNECTOR_API_VERSION = 1


class CapabilityError(RuntimeError):
    """A connector required a capability the runtime cannot provide."""


@dataclass(frozen=True)
class Capabilities:
    """What a runtime can do / what a connector needs.

    Defaults: buffered + streaming HTTP and POST are available everywhere;
    impersonation is per-source opt-in; `render` is False because no render
    transport exists.
    """

    stream: bool = True
    post: bool = True
    impersonate: bool = False
    render: bool = False

    def missing(self, required: Capabilities) -> tuple[str, ...]:
        """Capability names required but not provided."""
        return tuple(
            f.name
            for f in fields(Capabilities)
            if getattr(required, f.name) and not getattr(self, f.name)
        )


def negotiate(
    *,
    provided: Capabilities,
    required: Capabilities,
    connector_api_version: int = CONNECTOR_API_VERSION,
    connector_name: str = "connector",
) -> Capabilities:
    """Fail fast at load when a connector cannot run on this runtime.

    Returns the provided capabilities so a caller can record what was negotiated.
    """
    if connector_api_version != CONNECTOR_API_VERSION:
        raise CapabilityError(
            f"{connector_name}: CONNECTOR_API_VERSION {connector_api_version} "
            f"!= runtime {CONNECTOR_API_VERSION}"
        )
    gaps = provided.missing(required)
    if gaps:
        raise CapabilityError(f"{connector_name}: runtime lacks capability {', '.join(gaps)}")
    return provided
