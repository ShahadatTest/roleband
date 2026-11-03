"""Fetch public companies' SEC data for the pay dataset.

    .venv/bin/python -m scripts.fetch_sec_filings                 # every mapped company
    .venv/bin/python -m scripts.fetch_sec_filings servicenow uber --reports 3

For each public company in `pay_sources/sec_companies.json` (slug -> ticker,
CIK), saves, raw and uninterpreted, into the git-ignored sources directory:

- `sec/companyfacts/<slug>.json`: the company's XBRL facts. Stock-based
  compensation expense per fiscal year is the reliable fact in it (award-level
  detail is dimensional and absent from this API).
- `sec/annual/<slug>/<accession>.htm`: the latest N annual reports (10-K, 20-F
  or 40-F), whose text states the vesting terms and the headcount.

`scripts.build_pay_observations` reads them into facts. An annual report
already on disk is not fetched again (an accession number never changes).

The SEC's fair-access rules: a User-Agent that declares who is asking and how
to reach them, and at most 10 requests a second; this sends one every 0.2 s.
Public data. The contact is the operator's own, never a default: `--contact`
or `ROLEBAND_SEC_CONTACT` (an email address).

A 404 is a company with no such data. Any other answer that is not a 200 (a
403 or 429 refusal, a server error) is the SEC not answering: it is reported
as refused, never as absent, and the command exits 1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

from tracker.platform.paths import DATA_DIR

SOURCES_DIR = DATA_DIR / "level-atlas-sources"
COMPANIES = Path(__file__).with_name("pay_sources") / "sec_companies.json"
USER_AGENT = "RoleBand job-research tool (personal, non-commercial)"
CONTACT_ENV = "ROLEBAND_SEC_CONTACT"
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
_DELAY = 0.2


def annual_reports(submissions: dict, limit: int) -> list[dict]:
    """The latest `limit` annual reports, newest first, from a submissions document."""
    recent = submissions["filings"]["recent"]
    rows = [
        {"form": form, "accession": acc, "filed": filed, "report_date": period, "document": doc}
        for form, acc, filed, period, doc in zip(
            recent["form"], recent["accessionNumber"], recent["filingDate"],
            recent["reportDate"], recent["primaryDocument"], strict=True)
        if form in ANNUAL_FORMS and doc
    ]
    rows.sort(key=lambda r: r["filed"], reverse=True)
    return rows[:limit]


def document_url(cik: int, report: dict) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{report['accession'].replace('-', '')}/{report['document']}"


class Fetcher:
    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def get(self, url: str) -> httpx.Response:
        try:
            return self._client.get(url)
        finally:
            time.sleep(_DELAY)


def user_agent(contact: str | None) -> str:
    """The declared identity, with the operator's contact; refused without one."""
    contact = (contact or "").strip()
    if "@" not in contact:
        raise SystemExit(
            f"the SEC asks automated clients to declare a contact: pass --contact you@example.com "
            f"or set {CONTACT_ENV}")
    return f"{USER_AGENT} {contact}"


def fetch(slug: str, cik: int, out: Path, fetcher: Fetcher, reports: int) -> dict:
    result: dict = {"slug": slug, "cik": cik, "facts": False, "reports": [], "refused": []}

    def answered(response: httpx.Response) -> bool:
        if response.status_code not in (200, 404):
            result["refused"].append(f"{response.status_code} {response.request.url}")
        return response.status_code == 200

    facts = fetcher.get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json")
    if answered(facts):
        (out / "companyfacts").mkdir(parents=True, exist_ok=True)
        (out / "companyfacts" / f"{slug}.json").write_bytes(facts.content)
        result["facts"] = True
    subs = fetcher.get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    if not answered(subs):
        return result
    folder = out / "annual" / slug
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for report in annual_reports(subs.json(), reports):
        target = folder / f"{report['accession']}.htm"
        if not target.exists():
            doc = fetcher.get(document_url(cik, report))
            if not answered(doc):
                continue
            target.write_bytes(doc.content)
        index.append(report)
    (folder / "index.json").write_text(json.dumps(index, indent=1) + "\n", encoding="utf-8")
    result["reports"] = [r["form"] + " " + r["report_date"] for r in index]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("slugs", nargs="*", help="companies to fetch (default: every mapped company)")
    parser.add_argument("--reports", type=int, default=3, help="annual reports per company")
    parser.add_argument("--dir", type=Path, default=SOURCES_DIR, help="pay sources directory (git-ignored)")
    parser.add_argument("--contact", default=os.environ.get(CONTACT_ENV),
                        help=f"your email, declared to the SEC in the User-Agent (default: ${CONTACT_ENV})")
    args = parser.parse_args(argv)
    agent = user_agent(args.contact)
    companies = json.loads(COMPANIES.read_text(encoding="utf-8"))
    slugs = args.slugs or sorted(companies)
    out = args.dir / "sec"
    refused = 0
    with httpx.Client(headers={"User-Agent": agent}, timeout=60, follow_redirects=True) as client:
        fetcher = Fetcher(client)
        for slug in slugs:
            r = fetch(slug, companies[slug]["cik"], out, fetcher, args.reports)
            print(f"{slug}: facts={'yes' if r['facts'] else 'no'} reports={r['reports']}", flush=True)
            for line in r["refused"]:
                print(f"{slug}: REFUSED {line}", file=sys.stderr, flush=True)
            refused += len(r["refused"])
    if refused:
        print(f"{refused} request(s) refused; the data above is incomplete", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
