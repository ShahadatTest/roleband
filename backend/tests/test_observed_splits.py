"""The measured split a (company, band) reads is chosen, never left to row order.

Microsoft publishes 65, 66 and 67, and all three are `principal`. Many
(company, band) keys have conflicting rows, so letting whichever row Postgres
returns last win would let an UPDATE that rewrites a tuple change a chart. The
observed splits behind the stock trajectory and the equity check read the rung
`comp_package.choose_rung_row` picks, the same row the package beside them reads.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from tracker.api.routers.statistics import _observed_splits
from tracker.db.models import CompanyCompLevel, CompanyProfile
from tracker.levels.pay import pay_label
from tracker.schema import LevelBand
from tracker.taxonomy.comp_families import REFERENCE_FAMILY

pytestmark = pytest.mark.asyncio

# (label, stock share): only the declared rung's share is the right answer.
_PRINCIPAL = [("65", 0.21), ("66", 0.27), ("67", 0.40)]


def _rung(label: str, stock: float, base: int) -> CompanyCompLevel:
    return CompanyCompLevel(
        company_slug="microsoft", family=REFERENCE_FAMILY, level_label=label, band="principal",
        base_amount=base, base_pct=1 - stock - 0.1, stock_pct=stock, bonus_pct=0.1,
        # A core source: another source's row is read only through its plugin,
        # and these tests are about the split, not the source.
        provider="manual", fetched_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


async def _seed(db_session) -> None:
    db_session.add(CompanyProfile(slug="microsoft", display_name="Microsoft"))
    await db_session.flush()
    for n, (label, stock) in enumerate(_PRINCIPAL):
        db_session.add(_rung(label, stock, 200_000 + n * 20_000))
    await db_session.flush()


async def test_a_band_with_several_rungs_reads_the_declared_rung(db_session):
    assert pay_label("microsoft", LevelBand.PRINCIPAL) == "65", "the fixture assumes the atlas pins 65"
    await _seed(db_session)
    assert (await _observed_splits(db_session))[("microsoft", "principal")]["stock_pct"] == 0.21


async def test_rewriting_a_row_cannot_change_the_answer(db_session):
    """An UPDATE writes a new tuple, which Postgres then returns last: if the
    last row won, touching the declared rung would move the answer to it, and
    touching another rung would move it away."""
    await _seed(db_session)
    before = await _observed_splits(db_session)
    for label in ("65", "67", "66"):
        await db_session.execute(
            update(CompanyCompLevel)
            .where(CompanyCompLevel.level_label == label)
            .values(fetched_at=datetime(2026, 10, 2, tzinfo=UTC))
        )
        await db_session.flush()
        assert await _observed_splits(db_session) == before, f"touching {label} moved the split"
