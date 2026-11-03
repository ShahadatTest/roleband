"""Every slug the API can send has a name in the dashboard's catalog.

The backend keeps slugs and their meaning; the dashboard names them from
`dashboard/src/copy/en/vocab.ftl` (`src/copy/vocab.ts`). A slug added here
without its message would reach the screen as the slug itself, so the tables
are read from their owners and each is checked against the catalog's keys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tracker.analytics.velocity import AGING_BANDS
from tracker.company_discovery import SECTORS
from tracker.profiles.sources import SOURCES
from tracker.skills.catalog import get_catalog
from tracker.taxonomy.domains import DOMAIN_GROUPS
from tracker.taxonomy.roles import ROLE_GROUPS
from tracker.taxonomy.tracks import TRACKS

VOCAB = Path(__file__).resolve().parents[2] / "dashboard" / "src" / "copy" / "en" / "vocab.ftl"


def _part(slug: str) -> str:
    """`src/copy/vocab.ts` `part`: the slug as a catalog key part."""
    return re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")


def _keys() -> set[str]:
    return set(re.findall(r"^(vocab-[a-z0-9-]+) =", VOCAB.read_text(), re.MULTILINE))


TABLES = {
    "domain": [g.slug for g in DOMAIN_GROUPS] + ["unclassified"],
    "domain-hint": [g.slug for g in DOMAIN_GROUPS],
    "track": [t.slug for t in TRACKS],
    "role": [r.slug for r in ROLE_GROUPS] + ["other"],
    "sector": [s.slug for s in SECTORS],
    "source": list(SOURCES),
    "skill": [c.slug for c in get_catalog().concepts],
}


@pytest.mark.parametrize("kind", sorted(TABLES))
def test_every_slug_has_a_name(kind):
    keys = _keys()
    missing = [slug for slug in TABLES[kind] if f"vocab-{kind}-{_part(slug)}" not in keys]
    assert not missing, f"{kind} slugs with no message in {VOCAB.name}: {missing}"


def test_no_two_slugs_share_a_key():
    """`ai_ml` and `ai-ml` would read one message: the key part must stay unique."""
    for kind, slugs in TABLES.items():
        parts = [_part(slug) for slug in slugs]
        assert len(parts) == len(set(parts)), kind


def test_the_check_reads_the_catalog():
    """Negative control: a name the catalog does not hold is not found."""
    assert "vocab-domain-not-a-domain" not in _keys()
    assert len(_keys()) > 150


def test_every_age_band_has_a_name():
    """The Pace bars name each fixed band by its lower bound (`statistics/names.ts`)."""
    insights = (VOCAB.parent / "insights.ftl").read_text()
    missing = [lo for lo, _hi in AGING_BANDS if f"\ninsights-aging-from-{lo}-days =" not in insights]
    assert not missing, f"age bands with no name in insights.ftl: {missing}"
