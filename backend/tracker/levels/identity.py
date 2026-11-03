"""Who each company is, from the atlas (`company_identity.csv`), loaded once.

Identity is ours. Every module that asks whether a
company trades, under which ticker, or which listed stock its equity grants
track, asks here, so no second ticker table can drift from the file.
`scripts.check_company_listings` holds the file to the SEC.
"""

from __future__ import annotations

from tracker.levels.atlas import load_identity
from tracker.levels.model import CompanyIdentity

IDENTITIES: dict[str, CompanyIdentity] = load_identity()

#: Exchanges whose daily closes the price feed carries. A listing elsewhere
#: (Tokyo, Euronext) keeps its ticker in the atlas and is not priced.
PRICED_EXCHANGES = frozenset({"NYSE", "Nasdaq"})


def identity_for(slug: str) -> CompanyIdentity | None:
    """Our dataset's identity record for a company, or None: not one we hold."""
    return IDENTITIES.get(slug)


def listed_ticker(slug: str) -> str | None:
    """The company's own ticker, when the atlas says it is listed."""
    identity = IDENTITIES.get(slug)
    return identity.ticker if identity is not None and identity.listed else None


def grant_ticker(slug: str) -> str | None:
    """The parent's ticker a subsidiary's equity grants track, or None."""
    identity = IDENTITIES.get(slug)
    return identity.grant_ticker if identity is not None else None


def priced(ticker: str) -> bool:
    """Whether the price feed should be asked for this ticker. A ticker the
    atlas lists on an exchange outside `PRICED_EXCHANGES` is not; a ticker
    the atlas does not name (a parent, a company outside it) is."""
    for identity in IDENTITIES.values():
        if identity.ticker == ticker and identity.exchange:
            return identity.exchange in PRICED_EXCHANGES
    return True
