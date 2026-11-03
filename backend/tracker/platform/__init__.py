"""L0 platform primitives — product-agnostic infrastructure.

Rule (docs/architecture.md): nothing in this package imports any
other tracker module. Consumers pass configuration in as arguments.
"""

from __future__ import annotations

__all__ = [
    "breaker",
    "drift",
    "heartbeat",
    "http",
    "locks",
    "paging",
    "paths",
    "ratelimit",
    "util",
]
