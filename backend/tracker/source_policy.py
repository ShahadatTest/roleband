"""Static collection policy vocabulary; no database or transport dependencies.

`collection_access` is the ONE decision point for whether a request may be
made (`docs/sources.md`, "How a request is decided"). It answers two
questions and keeps them apart:

* **Operator deny** — `Settings.sync_policy_denied_providers`, a provider-level
  hard stop that no user action lifts.
* **Walled and not consented** — a source whose register row records a wall (`source_review.Wall`) is collected
  for a company only when the user followed that company through a consent
  dialog. The user is asked once: a consent stands when the register later
  records a changed robots file, a different wall or a stronger tier, because
  the question for the user is the same.
  Consent is COMPANY-level, so it is checked only when the caller names the
  company; a provider-level question (the scheduler's provider table, a bare
  transport) is answered by the operator deny alone. Every execution path that
  collects names its company and passes the consent it loaded.

It also releases the **fetch tier**: a walled,
consented company is fetched with its register row's `fetch_tier`; every other
answer carries `FetchTier.IDENTIFIED`. A provider-level question never gets a
tier above identified, because consent is per company.

No database access here: the caller reads the stored consent fingerprint off
the company's row and passes it in, which keeps this module importable by
transports, recipes and scripts alike.
"""

from __future__ import annotations

from dataclasses import dataclass

from tracker.config import Settings, get_settings
from tracker.source_review import FetchTier, declared_adapter, source_wall, user_directed_source

__all__ = [
    "CollectionAccess",
    "CollectionPolicyDenied",
    "FetchTier",
    "collection_access",
    "scanned_automatically",
]


class CollectionPolicyDenied(PermissionError):
    """Local denial, never evidence of source failure or disappearance."""

    def __init__(self, access: CollectionAccess):
        self.access = access
        super().__init__(access.reason)


@dataclass(frozen=True)
class CollectionAccess:
    provider_key: str
    reason: str | None = None
    #: The refusal is a wall awaiting the user's consent, not an operator deny.
    #: Reported apart so a screen can offer the consent rather than a dead end.
    walled: bool = False
    #: The fetch tier this request may use. `IDENTIFIED` unless
    #: the company is walled AND consented, when it is the register row's own
    #: tier. Released here and nowhere else, so no path can escalate on its own.
    tier: FetchTier = FetchTier.IDENTIFIED

    @property
    def denied(self) -> bool:
        """For gates that report or refuse rather than execute (scheduler, ops)."""
        return self.reason is not None

    def require(self) -> None:
        if self.reason is not None:
            raise CollectionPolicyDenied(self)


def collection_access(
    provider_key: str,
    *,
    company: str | None = None,
    settings: Settings | None = None,
    consent: str | None = None,
) -> CollectionAccess:
    """May RoleBand collect this provider (for this company)?

    Known company identity survives alternate execution (notably recipes): a
    recipe for a named company (a built-in, a catalog row or a connector
    family's company, `source_review.declared_adapter`) cannot shed its
    declared provider's deny or wall. `consent` is the fingerprint stored when
    the user consented (`TrackedCompany.consent_fingerprint`). Any stored
    consent unlocks the wall: the fingerprint records what was agreed and is
    never compared with the register's current one.
    """
    settings = settings if settings is not None else get_settings()
    declared_provider = declared_adapter(company, provider_key)
    for candidate in (provider_key, declared_provider):
        if candidate in settings.sync_policy_denied_providers:
            return CollectionAccess(candidate, f"provider {candidate!r} denied by collection policy")
    if company is not None:
        walled = source_wall(provider_key, company=company)
        if walled is not None and not consent:
            return CollectionAccess(
                walled.provider,
                f"{company!r} is walled ({walled.wall}) and the user has not consented to collecting it",
                walled=True,
            )
        if walled is not None:
            return CollectionAccess(provider_key, tier=walled.fetch_tier)
    return CollectionAccess(provider_key)


def scanned_automatically(
    provider_key: str,
    company: str,
    consent: str | None,
    *,
    settings: Settings | None = None,
) -> bool:
    """Whether RoleBand scans this followed company without the user asking.

    Operator policy and walls without the user's consent prevent collection.
    User-directed sources run only when the user asks. Coverage therefore
    rings only for allowed companies on automatically scanned sources.
    """
    access = collection_access(provider_key, company=company, settings=settings, consent=consent)
    return not access.denied and not user_directed_source(provider_key)
