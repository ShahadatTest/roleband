"""The repair pass for pay sections a section carve severed.

The selector is the whole design: the source payload a section was cut from is not
retained, so the severance can only be recognised by its SHAPE: a promoted pay section
that starts mid-sentence. A selector that also matched well-formed sections
would re-fetch the entire corpus; one that matched nothing would repair nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from scripts import backfill_severed_pay_sections as severed
from scripts import refetch_descriptions
from scripts.backfill_severed_pay_sections import is_severed
from tracker.db.models import Job


def _sections(pay: str | None, *, key: str = "pay_and_benefits") -> list[dict]:
    body = {"key": "qualifications", "title": "Qualifications", "content": "5+ years."}
    if pay is None:
        return [body]
    return [body, {"key": key, "title": "Compensation", "content": pay}]


def test_a_section_starting_mid_word_is_severed():
    """A promoted pay section opening mid-word must be selected for repair."""
    assert is_severed(
        _sections(
            "e pay range for this role across the U.S. is USD $155,800 - $277,200 per year."
        )
    )


def test_a_section_starting_at_a_sentence_is_not_severed():
    assert not is_severed(
        _sections(
            "Business Analytics M6 - The typical base pay range for this role across "
            "the U.S. is USD $155,800 - $277,200 per year."
        )
    )


def test_a_section_starting_on_a_figure_is_not_severed():
    """A declaration or currency amount is a valid pay-section opening.
    Selecting either would re-fetch intact sections unnecessarily."""
    assert not is_severed(_sections("The base salary range for this position is listed below."))
    assert not is_severed(_sections("$240,000 - $334,000 (USD) + 25% bonus target"))


def test_no_pay_section_and_no_sections_are_both_untouched():
    assert not is_severed(_sections(None))
    assert not is_severed([])
    assert not is_severed(None)
    assert not is_severed("not a list")


def test_only_the_pay_section_is_judged():
    """A body section may legitimately start lowercase — it is a continuation of the
    posting, not a promoted quote. Judging it would select the whole corpus."""
    assert not is_severed(_sections("continuing from the paragraph above.", key="responsibilities"))


def test_an_empty_pay_section_is_not_severed():
    assert not is_severed(_sections("   "))


# --- the re-read: paced like a scan, and only where policy lets us read -----------

SEVERED = "e pay range for this role across the U.S. is USD $155,800 - $277,200 per year."
FRESH_HTML = (
    "<div><h3>Qualifications</h3><p>5+ years.</p><h3>Compensation</h3>"
    "<p>The typical base pay range for this role is USD $155,800 - $277,200 per year.</p></div>"
)


class FakeAdapter:
    def __init__(self, calls: list[str]):
        self.calls = calls
        self.drift = SimpleNamespace(note=lambda *a, **k: None)
        self.name = "fake"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def hydrate(self, raw):
        self.calls.append(raw.req_id)
        raw.description_html = FRESH_HTML


def _job(n: int, company: str) -> Job:
    when = datetime(2026, 10, 1, tzinfo=UTC)
    return Job(
        company=company, req_id=f"r{n}", dedupe_key=f"{company}:r{n}", title="Analyst",
        url=f"https://example.com/jobs/{n}", status="open", in_scope=False, level_band="senior",
        level_confidence="confirmed", level_basis="stated", family="engineering", track="ic",
        locations=["United States"], location_groups=["us"], domains=[], first_seen=when, last_seen=when,
        description_text=SEVERED, description_sections=_sections(SEVERED), description_fetched_at=when,
    )


@pytest.mark.asyncio
async def test_the_re_read_shares_one_paced_adapter_per_company_and_skips_what_policy_refuses(
    db_session, scratch_scope, monkeypatch
):
    targets = {
        "google": {"adapter": "google", "consent": "yes"},
        "acme": {"adapter": "greenhouse", "board_token": "acme", "board_region": "eu"},
        "walled": {"adapter": "google", "consent": None},
    }

    async def get_active_targets(session):
        return targets

    built: list[tuple[str, dict]] = []
    calls: list[str] = []

    def build_adapter(slug, adapter_name, board_token=None, **kwargs):
        built.append((slug, kwargs))
        return FakeAdapter(calls)

    monkeypatch.setattr(severed, "get_active_targets", get_active_targets)
    monkeypatch.setattr(refetch_descriptions, "build_adapter", build_adapter)
    monkeypatch.setattr(severed, "build_adapter", build_adapter, raising=False)
    monkeypatch.setattr(
        refetch_descriptions, "collection_access",
        lambda key, company, consent: SimpleNamespace(denied=company == "walled"),
    )
    db_session.add_all([_job(1, "google"), _job(2, "google"), _job(3, "acme"), _job(4, "walled")])
    await db_session.commit()

    result = await severed.run(apply=True, company=None, limit=None)

    assert sorted(slug for slug, _ in built) == ["acme", "google"], "one adapter per company, none for a refused one"
    pools = {id(kw.get("limiter_pool")) for _, kw in built}
    breakers = {id(kw.get("breaker_pool")) for _, kw in built}
    assert all(kw.get("limiter_pool") is not None and kw.get("breaker_pool") is not None for _, kw in built)
    assert len(pools) == 1 and len(breakers) == 1, "every company on one pacer and one breaker pool"
    by_slug = dict(built)
    assert by_slug["acme"]["board_region"] == "eu"
    assert by_slug["google"]["consent"] == "yes"
    assert sorted(calls) == ["r1", "r2", "r3"], "the refused company's row is never fetched"
    assert result["denied"] == ["walled"]
    assert result["found"] == {"google": 2, "acme": 1, "walled": 1}
