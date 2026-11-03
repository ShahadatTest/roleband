"""The single place a model backend is CONSTRUCTED. Callers never build one.

`build_provider` returns the Apple Foundation Models provider, and is reached
ONLY by the Settings > Experimental self-test. Apple FM is deliberately not in
the routing ladder: it is available on one OS, on recent hardware, behind a user
setting, so nothing the app does automatically may depend on it. Salary
extraction is deterministic and lives in `tracker.pay_disclosure` with no
provider at all.

Enablement lives HERE, not in the provider: when the user has the experimental
integration off we hand back a `NullProvider(DISABLED_BY_FLAG)`, so
`AppleFMProvider.availability()` is free to report only what the *device* can do.
That split is what lets Settings distinguish "you turned it off" from "this Mac
can't run it".

Assembling the ladder needs the saved profiles and the egress switch, so it is
service work and lives in `tracker/intelligence_runtime/routing.py`.
"""

from __future__ import annotations

from tracker.intelligence.apple_fm import AppleFMProvider
from tracker.intelligence.provider import AvailabilityState, IntelligenceProvider, NullProvider

# Cache the Apple provider so its SDK import happens once.
_apple: AppleFMProvider | None = None


def build_provider(enabled: bool) -> IntelligenceProvider:
    """The EXPERIMENTAL Apple Foundation Models provider, or a Null one.

    Pure — no DB, no settings read. This is not part of any automatic path: the
    only caller is the Settings > Experimental self-test, which exists to keep
    the integration exercisable for whenever Apple's on-device model grows a
    capability worth routing to.
    """
    global _apple
    if not enabled:
        return NullProvider(AvailabilityState.DISABLED_BY_FLAG, "integration is turned off")
    if _apple is None:
        _apple = AppleFMProvider()
    return _apple
