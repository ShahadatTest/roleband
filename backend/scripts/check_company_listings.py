"""Does every listed company in our dataset still trade under the ticker the atlas says?

Run monthly. Tickers move under us: Block went SQ -> XYZ,
Marsh McLennan MMC -> MRSH, Wise moved its primary listing to Nasdaq as WSE, and
IBM's purchase of Confluent ended CFLT. A wrong ticker is the quiet failure: a
renamed symbol may still quote, and the price pass would chart another company.

For each `company_identity.csv` row with a `cik`, one request to the SEC's
submissions record (data.sec.gov, paced under its fair-access limit) names the
registrant, its tickers and their exchanges. The `cik` is what makes this work: it
survives a rename, so the record is found when the symbol is not.

Findings (the comparison is `compare`, pure and tested offline):

    renamed    the atlas ticker is not among the registrant's tickers
    delisted   the registrant has no ticker any more (acquired, taken private)
    exchange   the atlas exchange differs from the SEC's for that ticker
    unlisted   the atlas says not listed, yet the registrant has a ticker
    no_cik     listed on a US exchange (or none named) with no `cik` to check

A listing outside the US (Tokyo, Euronext) has no SEC record; it is printed as
checked by hand, never a finding.

Exit codes, as `check_vendored_upstream`:

    0  every checked row agrees with the SEC
    1  FINDINGS: fix the atlas row (and its `note`)
    3  UNKNOWN: a request failed; nothing was decided for that row

Usage (from `backend/`):

    .venv/bin/python -m scripts.check_company_listings
    .venv/bin/python -m scripts.check_company_listings block figma
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass

import httpx

from tracker.levels.atlas import load_identity
from tracker.levels.model import CompanyIdentity

USER_AGENT = "RoleBand job-research tool (personal, non-commercial)"
#: The SEC asks for at most 10 requests a second.
_DELAY = 0.2
#: Exchanges the SEC records a registrant's tickers on. A listing elsewhere is checked by hand.
US_EXCHANGES = frozenset({"NYSE", "Nasdaq", "CBOE"})


@dataclass(frozen=True)
class Finding:
    company: str
    kind: str
    detail: str


def compare(identity: CompanyIdentity, record: dict) -> list[Finding]:
    """What an SEC submissions record says against the atlas row. Empty: they agree."""
    tickers = [t for t in record.get("tickers") or [] if t]
    exchanges = list(record.get("exchanges") or [])
    name = record.get("name") or "?"
    slug = identity.slug
    if identity.listed is False:
        if tickers:
            return [Finding(slug, "unlisted", f"{name} trades as {tickers[0]} on {_exchange_of(tickers[0], tickers, exchanges)}")]
        return []
    if not tickers:
        return [Finding(slug, "delisted", f"{name} has no ticker any more (was {identity.ticker or 'none recorded'})")]
    if identity.ticker is None:
        return [Finding(slug, "renamed", f"no ticker recorded; {name} trades as {tickers[0]}")]
    if identity.ticker not in tickers:
        return [Finding(slug, "renamed", f"{identity.ticker} is not {name}'s; it trades as {', '.join(tickers)}")]
    exchange = _exchange_of(identity.ticker, tickers, exchanges)
    if identity.exchange != exchange:
        return [Finding(slug, "exchange", f"{identity.ticker} trades on {exchange}, the atlas says {identity.exchange or 'nothing'}")]
    return []


def _exchange_of(ticker: str, tickers: list[str], exchanges: list[str]) -> str:
    i = tickers.index(ticker)
    return exchanges[i] if i < len(exchanges) and exchanges[i] else "?"


def unchecked(identity: CompanyIdentity) -> Finding | None:
    """A listed row with no `cik`: a finding on a US exchange, hand-checked elsewhere."""
    if identity.listed is not True or identity.cik is not None:
        return None
    if identity.exchange and identity.exchange not in US_EXCHANGES:
        return None
    return Finding(identity.slug, "no_cik", f"listed as {identity.ticker or '?'} with no SEC number to check it by")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("companies", nargs="*", help="slugs to check (default: every row)")
    args = parser.parse_args(argv)
    identities = load_identity()
    rows = [identities[s] for s in args.companies] if args.companies else list(identities.values())
    findings: list[Finding] = []
    failed: list[str] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as client:
        for identity in rows:
            if (gap := unchecked(identity)) is not None:
                findings.append(gap)
                continue
            if identity.cik is None:
                if identity.listed:
                    print(f"{identity.slug}: {identity.ticker} on {identity.exchange}, outside the SEC: checked by hand")
                continue
            try:
                r = client.get(f"https://data.sec.gov/submissions/CIK{identity.cik:010d}.json")
                r.raise_for_status()
                record = r.json()
            except (httpx.HTTPError, ValueError) as exc:
                failed.append(f"{identity.slug}: {exc}")
                continue
            finally:
                time.sleep(_DELAY)
            found = compare(identity, record)
            findings.extend(found)
            if not found:
                print(f"{identity.slug}: ok ({identity.ticker or 'not listed'}, {record.get('name')})")
    for f in findings:
        print(f"FINDING {f.kind:9} {f.company}: {f.detail}")
    for line in failed:
        print(f"UNKNOWN {line}")
    print(f"{len(rows)} rows, {len(findings)} findings, {len(failed)} unknown")
    if findings:
        return 1
    return 3 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
