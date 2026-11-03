"""Realistic rows for the tracked-company contract.

Every timestamp is fixed, so two runs of the same request return the same bytes.
The rows cover each branch `_company_out`, `build_company_discovery` and the
company routes can take:

| row | what it exercises |
|---|---|
| `google` | a built-in: `source=builtin`, `connector_state=live`, cannot be removed |
| `stripe` | a catalog greenhouse board with a discovery careers URL: `connector_state=ready`, catalog `ready` |
| `mckinsey-company` | a discovery company with no connector: `pending`, `connector_state=planned`, never scanned |
| `acme-labs` | URL-added outside the discovery catalog: `source=url`, catalog `partial` with an error, no sectors |
| `hidden-co` | URL-added, not visible and not enabled, with no careers URL |

Open-role counts come from `google` (two in scope, one closed, one out of scope),
`stripe` (one) and `hidden-co` (one), so every count rule is visible.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import T0, make_company, make_job
from tracker.db.models import Job


def company_job(company: str, key: str, **over) -> Job:
    """A staff software engineer posting at `company` in London, the shape
    every open-role count here is made of; `over` replaces any field."""
    row = {
        "title": f"Staff Software Engineer, {key}",
        "url": f"https://careers.example.test/{company}/{key}",
        "department": None,
        "locations": ["London, UK"],
        "location_groups": ["uk"],
        "family": "software_engineering",
        "track": "technical",
    }
    row.update(over)
    return make_job(key, company=company, **row)


async def seed_company_contract(session: AsyncSession) -> None:
    session.add_all([
        make_company("google", "Google", adapter="google", board_token=None, careers_url=None, source="builtin"),
        make_company("stripe", "Stripe", careers_url="https://stripe.com/jobs"),
        make_company(
            # This row exists for the no-connector branch, so it names a company
            # that has no connector; a company that gains one moves this row to
            # another rather than weakening the assertion.
            "mckinsey-company", "McKinsey & Company", adapter=None, board_token=None,
            careers_url="https://www.mckinsey.com/careers/search-jobs",
            status="pending", role_catalog_status="pending", role_catalog_scanned_at=None,
        ),
        make_company(
            "acme-labs", "Acme Labs", board_token="acmelabs",
            careers_url="https://job-boards.greenhouse.io/acmelabs", source="url",
            role_catalog_status="partial", role_catalog_error="HTTPError: 503 on page 2",
        ),
        make_company(
            "hidden-co", "Hidden Co", adapter=None, board_token=None, careers_url=None,
            status="pending", enabled=False, visible=False, source="url",
            role_catalog_status="pending", role_catalog_scanned_at=None,
        ),
    ])
    session.add_all([
        company_job("google", "one"),
        company_job("google", "two"),
        company_job("google", "closed", status="closed", closed_at=T0),
        company_job("google", "out_of_scope", in_scope=False),
        company_job("stripe", "one"),
        company_job("hidden-co", "one"),
    ])
    await session.commit()
