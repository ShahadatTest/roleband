"""Drop the searched country from stored Google place lists that already name it.

Google's listing is searched one country at a time, and a card folds its later
places into "+2 more", so the adapter records the searched country beside the
card's own places. Where a listed place already lies in that country, the extra
entry only says the country again and shows as a place of its own
("Sunnyvale, CA, USA", "United States"). The adapter adds it only where no
listed place lies there, and a scan rewrites the rows it lists, so this repairs
the rest: closed postings, and inventory rows no scan reads again.

A row is rewritten when its last place is a country's search term, a place
before it already lies in that country (`countries_for`, the adapter's own
test), and dropping it moves neither the row's location groups nor its cities.
Only `locations` is written, so scope, place filters and pay keys read exactly
what they read before. An inventory row's `content_hash` is left as it was:
the next scan of that posting sees a different hash and rewrites the row once.

Dry-run by default. `--apply` writes in batches of `BATCH` rows, each its own
transaction; a rerun selects only rows that still end in a search term, and
skips those the rule keeps, so it resumes by itself.

Run from backend/:
    .venv/bin/python -m scripts.backfill_google_places            # dry run
    .venv/bin/python -m scripts.backfill_google_places --apply    # write
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy import func, select

from tracker.db.models import Job, PostingInventory
from tracker.db.session import commit_in_batches, session_scope
from tracker.enrich.classify import location_slugs_for
from tracker.taxonomy.countries import COUNTRIES
from tracker.taxonomy.locations import countries_for, normalize_cities

log = logging.getLogger(__name__)

#: Rows per transaction: the most a killed `--apply` can lose.
BATCH = 500

#: Every google-adapter posting URL starts here, whichever company slug holds
#: it (google and google-deepmind share the board).
JOB_URL_PREFIX = "https://www.google.com/about/careers/applications/jobs/results/"

#: The adapter's search terms (`GOOGLE_LOCATION_QUERIES`), each to its country.
SEARCH_TERM_COUNTRY = {country.query_name: country.slug for country in COUNTRIES}

TABLES = (Job, PostingInventory)


def without_search_term(places: list[str]) -> list[str] | None:
    """`places` without a trailing search term the places before it already
    cover, or None when the row keeps every place it has."""
    if len(places) < 2 or places[-1] not in SEARCH_TERM_COUNTRY:
        return None
    listed = places[:-1]
    if SEARCH_TERM_COUNTRY[places[-1]] not in countries_for(listed):
        return None
    if location_slugs_for(listed) != location_slugs_for(places):
        return None
    if normalize_cities(listed) != normalize_cities(places):
        return None
    return listed


def _candidates(model):
    last = model.locations[func.cardinality(model.locations)]
    return select(model.id).where(
        model.url.startswith(JOB_URL_PREFIX, autoescape=True),
        func.cardinality(model.locations) > 1,
        last.in_(list(SEARCH_TERM_COUNTRY)),
    )


async def backfill(apply: bool, batch: int = BATCH) -> dict[str, int]:
    pending: dict[str, list[int]] = {}
    async with session_scope() as session:
        for model in TABLES:
            rows = (
                await session.execute(
                    select(model.id, model.locations)
                    .where(model.id.in_(_candidates(model)))
                    .order_by(model.id)
                )
            ).all()
            pending[model.__tablename__] = [
                row.id for row in rows if without_search_term(list(row.locations)) is not None
            ]
    stats = {f"{name}_pending": len(ids) for name, ids in pending.items()}
    if not apply:
        return stats

    for model in TABLES:
        async def write(session, ids: list[int], model=model) -> int:
            rows = (await session.scalars(select(model).where(model.id.in_(ids)))).all()
            changed = 0
            for row in rows:
                clean = without_search_term(list(row.locations or []))
                if clean is not None:
                    row.locations = clean
                    changed += 1
            return changed

        stats[f"{model.__tablename__}_rewritten"] = await commit_in_batches(
            pending[model.__tablename__], write, size=batch, label=f"{model.__tablename__} places"
        )
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="persist (default: dry run)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    stats = asyncio.run(backfill(args.apply))
    log.info("google place backfill: %s", stats)
    if not args.apply and any(stats.values()):
        log.info("Dry run: nothing written. Re-run with --apply to persist.")


if __name__ == "__main__":
    main()
